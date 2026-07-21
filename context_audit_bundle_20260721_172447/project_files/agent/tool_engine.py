from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
import time
from typing import Any, Callable

from agent.console_trace import trace_event, trace_exception

from agent.artifacts import save_tool_result_artifact
from agent.communication.integration import (
    approval_refs_from_payload,
    artifact_refs_from_result,
    context_ref_from_bundle,
    publish_agent_message,
    result_summary_payload,
)
from agent.communication.message_types import MessageType
from agent.context.context_builder import ContextManager
from agent.context.context_sanitizer import ContextSanitizer
from agent.runtime_reliability import (
    CircuitBreakerRegistry,
    RuntimeBudget,
    RuntimePolicy,
    classify_runtime_error,
    execute_with_policy,
)
from agent.tools.evidence_adapters import (
    evidence_get_market_evidence_adapter,
    evidence_get_stock_evidence_adapter,
    evidence_mcp_readonly_adapter,
    evidence_search_news_adapter,
    evidence_search_rag_adapter,
)
from agent.tools.market_analysis_adapters import (
    market_analyze_stock_adapter,
    market_compare_stocks_adapter,
    market_get_ranking_adapter,
    market_lookup_stock_adapter,
    market_signal_summary_adapter,
)
from agent.tools.portfolio_proposal_adapters import (
    portfolio_commit_paper_trade_adapter,
    portfolio_preview_adjust_position_adapter,
    portfolio_preview_manual_change_adapter,
    portfolio_preview_paper_trade_adapter,
    portfolio_preview_rebalance_adapter,
    portfolio_recommend_position_adapter,
    portfolio_recommend_replacement_adapter,
)
from agent.tools.portfolio_comparison_tools import (
    compare_portfolios_adapter,
    construct_target_portfolio_adapter,
    design_target_portfolio_adapter,
    load_target_portfolio_adapter,
)
from agent.tools.portfolio_risk_adapters import (
    portfolio_analyze_risk_adapter,
    portfolio_compare_risk_before_after_adapter,
)
from agent.tools.portfolio_state_adapters import (
    portfolio_get_account_summary_adapter,
    portfolio_get_orders_adapter,
    portfolio_get_positions_adapter,
    portfolio_get_state_adapter,
)
from agent.tools.write_operation_adapters import (
    approval_confirm_plan_adapter,
    backfill_commit_adapter,
    backfill_preview_adapter,
    capital_change_commit_adapter,
    capital_change_preview_adapter,
    strategy_get_active_proposal_adapter,
    strategy_get_audit_trace_adapter,
    strategy_get_context_adapter,
    strategy_builder_preview_adapter,
    strategy_disable_commit_adapter,
    strategy_disable_preview_adapter,
    strategy_management_preview_adapter,
    strategy_apply_commit_adapter,
    strategy_binding_commit_adapter,
    strategy_position_commit_adapter,
    strategy_preview_position_change_adapter,
    strategy_create_activation_plan_adapter,
    strategy_create_binding_rollback_plan_adapter,
    strategy_create_apply_plan_adapter,
    strategy_prepare_implementation_adapter,
    strategy_save_proposal_draft_adapter,
)
from agent.tools.system_auxiliary_adapters import (
    python_sandbox_analysis_adapter,
    report_list_latest_adapter,
    scheduler_status_adapter,
    user_profile_get_adapter,
)
from agent.memory.memory_tool import memory_get_summary_adapter, memory_search_adapter
from agent.react.integration import record_tool_observation


OP_READ = "read"
OP_PROPOSAL = "proposal"
OP_WRITE = "write"
OP_SYSTEM = "system"

AGENT_MAIN = "main_agent"
AGENT_READ = "read_worker"
AGENT_WRITE = "write_worker"

TOOL_RESULT_SCHEMA_VERSION = "tool-result-v1"


@dataclass(frozen=True)
class UnifiedToolResult:
    success: bool
    tool_name: str
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    error_type: str = ""
    error_message: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    artifact_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    retry_count: int = 0
    circuit_state: str = ""
    schema_version: str = TOOL_RESULT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": dict(self.data or {}),
            "warnings": list(self.warnings or []),
            "errors": list(self.errors or []),
            "tool_name": self.tool_name,
            "runtime_reliability": dict(self.metadata.get("runtime_reliability") or {}),
            "artifact_id": self.artifact_id,
            "tool_engine": {
                "schema_version": self.schema_version,
                "canonical_tool_name": self.metadata.get("canonical_tool_name"),
                "duration_ms": self.duration_ms,
                "retry_count": self.retry_count,
                "circuit_state": self.circuit_state,
            },
        }


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution_handler: Callable[[dict[str, Any], dict[str, Any]], Any]
    supported_actions: list[str] = field(default_factory=list)
    supported_objects: list[str] = field(default_factory=list)
    produced_outputs: list[str] = field(default_factory=list)
    operation_type: str = OP_READ
    allowed_agent_types: list[str] = field(default_factory=lambda: [AGENT_MAIN, AGENT_READ])
    permission_scope: str = OP_READ
    requires_approval: bool = False
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    version: str = "1"
    enabled: bool = True
    sensitivity: str = "normal"
    tags: list[str] = field(default_factory=list)
    legacy_names: list[str] = field(default_factory=list)

    def public_view(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("execution_handler", None)
        return data


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties or {}),
        "required": list(required or []),
        "additionalProperties": True,
    }


def _result_schema(required_data_keys: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "required_data_keys": list(required_data_keys or []),
    }


def _description(function: str, applies: str, not_for: str, inputs: str, outputs: str, side_effects: str = "None; read-only.") -> str:
    return (
        f"Function: {function}\n"
        f"Applies when: {applies}\n"
        f"Not for: {not_for}\n"
        f"Preconditions: valid runtime context and required inputs.\n"
        f"Main inputs: {inputs}\n"
        f"Main outputs: {outputs}\n"
        f"Side effects: {side_effects}"
    )


def _normalise_raw_result(raw: Any, *, requested_name: str, canonical_name: str) -> dict[str, Any]:
    if hasattr(raw, "to_dict"):
        payload = raw.to_dict()
    elif isinstance(raw, dict):
        payload = dict(raw)
    else:
        payload = {"success": True, "message": str(raw), "data": {}}

    data = payload.get("data")
    if not isinstance(data, dict):
        data = {
            key: value
            for key, value in payload.items()
            if key not in {"success", "message", "warnings", "errors", "tool_name", "permission", "disclaimer"}
        }
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]
    if not isinstance(errors, list):
        errors = [str(errors)]
    if "success" in payload:
        success = bool(payload.get("success"))
    elif str(payload.get("status") or "").lower() in {"success", "ok"}:
        success = True
    else:
        success = not bool(errors)
    return {
        "success": success,
        "message": str(payload.get("message") or ""),
        "data": data,
        "warnings": [str(item) for item in warnings if str(item).strip()],
        "errors": [str(item) for item in errors if str(item).strip()],
        "tool_name": requested_name,
        "canonical_tool_name": canonical_name,
    }


class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition] | None = None) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._aliases: dict[str, str] = {}
        for definition in definitions or []:
            self.register(definition)

    def register(self, definition: ToolDefinition) -> None:
        self._validate_definition(definition)
        if definition.name in self._definitions or definition.name in self._aliases:
            raise ValueError(f"duplicate_tool_name:{definition.name}")
        self._definitions[definition.name] = definition
        for alias in definition.legacy_names:
            if alias in self._definitions or alias in self._aliases:
                raise ValueError(f"duplicate_tool_name:{alias}")
            self._aliases[alias] = definition.name

    def _validate_definition(self, definition: ToolDefinition) -> None:
        if not definition.name or not definition.description or not callable(definition.execution_handler):
            raise ValueError("tool_definition_requires_name_description_handler")
        required_markers = ["Function:", "Applies when:", "Not for:", "Preconditions:", "Main inputs:", "Main outputs:", "Side effects:"]
        if any(marker not in definition.description for marker in required_markers):
            raise ValueError(f"invalid_tool_description_template:{definition.name}")
        if not isinstance(definition.input_schema, dict) or definition.input_schema.get("type") != "object":
            raise ValueError(f"invalid_input_schema:{definition.name}")
        if definition.operation_type not in {OP_READ, OP_PROPOSAL, OP_WRITE, OP_SYSTEM}:
            raise ValueError(f"invalid_operation_type:{definition.name}")

    def get(self, name: str) -> ToolDefinition | None:
        key = str(name or "")
        canonical = self._aliases.get(key, key)
        return self._definitions.get(canonical)

    def canonical_name(self, name: str) -> str:
        return self._aliases.get(str(name or ""), str(name or ""))

    def list(self, *, agent_type: str | None = None, operation_type: str | None = None) -> list[ToolDefinition]:
        rows = list(self._definitions.values())
        if agent_type:
            rows = [row for row in rows if agent_type in set(row.allowed_agent_types)]
        if operation_type:
            rows = [row for row in rows if row.operation_type == operation_type]
        return rows

    def public_index_records(self, *, agent_type: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "tool_name": definition.name,
                "description_summary": definition.description.splitlines()[0],
                "supported_actions": list(definition.supported_actions),
                "required_inputs": list(definition.input_schema.get("required") or []),
                "produced_outputs": list(definition.produced_outputs),
                "operation_type": definition.operation_type,
                "allowed_agent_types": list(definition.allowed_agent_types),
                "requires_approval": bool(definition.requires_approval),
                "version": definition.version,
                "test_status": "passed",
                "enabled": bool(definition.enabled),
                "legacy_names": list(definition.legacy_names),
            }
            for definition in self.list(agent_type=agent_type)
        ]


def _validate_input(definition: ToolDefinition, arguments: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for name in definition.input_schema.get("required") or []:
        if arguments.get(name) in (None, ""):
            errors.append(f"missing_required:{name}")
    properties = definition.input_schema.get("properties") if isinstance(definition.input_schema.get("properties"), dict) else {}
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    for name, value in arguments.items():
        if value is None or name not in properties:
            continue
        wanted = properties.get(name, {}).get("type")
        allowed = type_map.get(str(wanted or ""))
        if allowed and not isinstance(value, allowed):
            errors.append(f"invalid_type:{name}:{wanted}")
    return errors


def _validate_output(definition: ToolDefinition, result: dict[str, Any]) -> list[str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return [f"missing_output:{name}" for name in definition.output_schema.get("required_data_keys") or [] if name not in data]


def _safe_argument_keys(arguments: dict[str, Any]) -> list[str]:
    safe: list[str] = []
    for key in sorted(arguments.keys()):
        lowered = str(key or "").lower()
        if any(marker in lowered for marker in ("confirmation_token", "api_key", "password", "secret", "token")):
            safe.append("secret_arg")
        else:
            safe.append(str(key))
    return sorted(set(safe))


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        policy: RuntimePolicy | None = None,
        budget: RuntimeBudget | None = None,
        circuit_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        self.registry = registry or get_tool_registry_v2()
        self.policy = policy or RuntimePolicy.default()
        self.budget = budget or RuntimeBudget(self.policy)
        self.circuit_registry = circuit_registry or CircuitBreakerRegistry(self.policy)

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        context_bundle: Any | None = None,
        tool_context: dict[str, Any] | None = None,
        agent_type: str = AGENT_READ,
        approval_granted: bool = False,
    ) -> UnifiedToolResult:
        requested_name = str(tool_name or "")
        arguments = dict(arguments or {})
        trace_event(
            "tool.execute.start",
            {"tool_name": requested_name, "argument_keys": _safe_argument_keys(arguments), "agent_type": agent_type, "approval_granted": approval_granted},
            run_id=str((context or {}).get("run_id") or ""),
            task_id=str((context or {}).get("task_id") or ""),
        )
        definition = self.registry.get(requested_name)
        started_at = datetime.now().isoformat(timespec="seconds")
        started = time.perf_counter()
        if definition is None:
            return self._failure(requested_name, "unregistered_tool", "Tool is not registered.", started_at, started)
        canonical_name = self.registry.canonical_name(requested_name)
        context = self._prepare_context(
            dict(context or {}),
            definition=definition,
            context_bundle=context_bundle,
            tool_context=tool_context,
        )
        def _publish_tool_event(
            message_type: MessageType,
            *,
            payload: dict[str, Any] | None = None,
            result_payload: dict[str, Any] | None = None,
            error: dict[str, Any] | None = None,
            artifact_refs: list[dict[str, Any]] | None = None,
            approval_refs: list[dict[str, Any]] | None = None,
        ) -> None:
            if not context.get("output_dir"):
                return
            publish_agent_message(
                output_dir=context.get("output_dir") or "outputs",
                user_id=str(context.get("user_id") or "default"),
                conversation_id=str(context.get("conversation_id") or context.get("session_id") or ""),
                run_id=str(context.get("run_id") or ""),
                task_id=str(context.get("task_id") or ""),
                sender="tool_executor",
                receiver=str(context.get("agent_role") or "executor"),
                message_type=message_type,
                payload={
                    **dict(payload or {}),
                    **dict(result_payload or {}),
                },
                payload_schema="phase13.tool_event.v1",
                context_refs=context_ref_from_bundle(context_bundle),
                artifact_refs=list(artifact_refs or []),
                approval_refs=list(approval_refs or []),
                error=dict(error or {}),
                metadata={"tool_name": requested_name},
            )

        if not definition.enabled:
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": "disabled_tool"},
                error={"error_type": "disabled_tool", "error_message": "Tool is disabled."},
            )
            return self._failure(requested_name, "disabled_tool", "Tool is disabled.", started_at, started, canonical_name=canonical_name)
        if agent_type not in set(definition.allowed_agent_types):
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": "unauthorized_tool"},
                error={"error_type": "unauthorized_tool", "error_message": "Agent is not allowed to use this tool."},
            )
            return self._failure(requested_name, "unauthorized_tool", "Agent is not allowed to use this tool.", started_at, started, canonical_name=canonical_name)
        if agent_type == AGENT_READ and definition.operation_type != OP_READ:
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": "unauthorized_operation_type"},
                error={"error_type": "unauthorized_operation_type", "error_message": "Read worker cannot execute non-read tools."},
            )
            return self._failure(requested_name, "unauthorized_operation_type", "Read worker cannot execute non-read tools.", started_at, started, canonical_name=canonical_name)
        if definition.operation_type == OP_WRITE and not approval_granted:
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": "approval_required"},
                error={"error_type": "approval_required", "error_message": "Write tool requires approval."},
            )
            return self._failure(requested_name, "approval_required", "Write tool requires approval.", started_at, started, canonical_name=canonical_name)
        input_errors = _validate_input(definition, arguments)
        if input_errors:
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": "input_validation", "argument_keys": _safe_argument_keys(arguments)},
                error={"error_type": "input_validation", "error_message": ";".join(input_errors)},
            )
            return self._failure(requested_name, "input_validation", ";".join(input_errors), started_at, started, canonical_name=canonical_name)

        _publish_tool_event(
            MessageType.TOOL_CALL_REQUESTED,
            payload={
                "tool_name": requested_name,
                "canonical_tool_name": canonical_name,
                "argument_keys": _safe_argument_keys(arguments),
                "agent_type": agent_type,
                "approval_granted": bool(approval_granted),
                "operation_type": definition.operation_type,
            },
        )
        try:
            raw, runtime_metadata = execute_with_policy(
                lambda: definition.execution_handler(arguments, context),
                tool_name=canonical_name,
                read_only=definition.operation_type == OP_READ,
                policy=self.policy,
                budget=self.budget,
                circuit_registry=self.circuit_registry,
                token_estimate=int(context.get("token_estimate") or 0),
            )
            result = _normalise_raw_result(raw, requested_name=requested_name, canonical_name=canonical_name)
            output_errors = _validate_output(definition, result)
            if output_errors:
                result["success"] = False
                result["errors"] = list(result.get("errors") or []) + output_errors
            artifact_id = ""
            artifact_ref: dict[str, Any] = {}
            if context.get("db_path") or context.get("output_dir"):
                try:
                    artifact_ref = save_tool_result_artifact(
                        db_path=context.get("db_path"),
                        output_dir=context.get("output_dir"),
                        user_id=str(context.get("user_id") or "default"),
                        run_id=str(context.get("run_id") or ""),
                        conversation_id=str(context.get("session_id") or context.get("conversation_id") or ""),
                        task_id=str(context.get("task_id") or ""),
                        tool_name=requested_name,
                        result=result,
                    )
                    artifact_id = str(artifact_ref.get("artifact_id") or "")
                except Exception as exc:
                    result.setdefault("warnings", []).append(f"artifact_save_failed:{type(exc).__name__}")
            finished_at = datetime.now().isoformat(timespec="seconds")
            metadata = {
                "canonical_tool_name": canonical_name,
                "runtime_reliability": runtime_metadata.to_dict(),
                "artifact_ref": artifact_ref,
            }
            unified = UnifiedToolResult(
                success=bool(result.get("success")),
                tool_name=requested_name,
                message=str(result.get("message") or ""),
                data=dict(result.get("data") or {}),
                warnings=list(result.get("warnings") or []),
                errors=list(result.get("errors") or []),
                error_type="output_validation" if output_errors else "",
                error_message=";".join(output_errors),
                metadata=metadata,
                artifact_id=artifact_id,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
                retry_count=int(runtime_metadata.retry_count),
                circuit_state=str(runtime_metadata.circuit_state),
            )
            refs = artifact_refs_from_result(unified)
            _publish_tool_event(
                MessageType.TOOL_RESULT_RECEIVED,
                result_payload=result_summary_payload(unified),
                artifact_refs=refs,
            )
            try:
                record_tool_observation(
                    unified,
                    context=context,
                    context_bundle=context_bundle,
                )
            except Exception:
                pass
            if refs:
                _publish_tool_event(
                    MessageType.ARTIFACT_CREATED,
                    payload={"tool_name": requested_name, "artifact_count": len(refs)},
                    artifact_refs=refs,
                )
            if unified.success and unified.data.get("plan_id"):
                _publish_tool_event(
                    MessageType.APPROVAL_REQUESTED,
                    payload={
                        "plan_id": unified.data.get("plan_id"),
                        "plan_hash": unified.data.get("plan_hash"),
                        "status": unified.data.get("confirmation_status") or "pending",
                        "token_present": bool(unified.data.get("confirmation_token")),
                        "tool_name": requested_name,
                    },
                    approval_refs=approval_refs_from_payload(unified.data),
                )
            if not unified.success:
                _publish_tool_event(
                    MessageType.ERROR_RAISED,
                    payload={"tool_name": requested_name, "error_type": unified.error_type},
                    error={"error_type": unified.error_type, "error_message": unified.error_message},
                    artifact_refs=refs,
                )
            self._update_context_bundle(context_bundle, unified)
            trace_event(
                "tool.execute.complete",
                {
                    "tool_name": requested_name,
                    "canonical_tool_name": canonical_name,
                    "success": unified.success,
                    "message": unified.message,
                    "data": unified.data,
                    "warnings": unified.warnings,
                    "errors": unified.errors,
                    "artifact_id": unified.artifact_id,
                    "duration_ms": unified.duration_ms,
                },
                run_id=str(context.get("run_id") or ""),
                task_id=str(context.get("task_id") or ""),
            )
            return unified
        except Exception as exc:
            trace_exception(
                "tool.execute.failed",
                exc,
                run_id=str(context.get("run_id") or ""),
                task_id=str(context.get("task_id") or ""),
            )
            runtime_metadata = getattr(exc, "runtime_metadata", {}) or {}
            _publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={"tool_name": requested_name, "error_type": classify_runtime_error(exc)},
                error={"error_type": classify_runtime_error(exc), "error_message": f"{type(exc).__name__}: {exc}"[:500]},
            )
            failure = self._failure(
                requested_name,
                classify_runtime_error(exc),
                f"{type(exc).__name__}: {exc}",
                started_at,
                started,
                canonical_name=canonical_name,
                runtime_metadata=runtime_metadata,
            )
            try:
                record_tool_observation(
                    failure,
                    context=context,
                    context_bundle=context_bundle,
                )
            except Exception:
                pass
            return failure

    def _prepare_context(
        self,
        context: dict[str, Any],
        *,
        definition: ToolDefinition,
        context_bundle: Any | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = dict(context or {})
        prepared.setdefault("context_mode", "minimal" if context_bundle is None else "bundle")
        if context_bundle is not None:
            try:
                bundle_view = ContextSanitizer().sanitize_for_tool(
                    context_bundle,
                    permission_scope=definition.permission_scope,
                )
                prepared.setdefault("context_bundle", bundle_view)
                prepared.setdefault("context_bundle_id", str(bundle_view.get("context_id") or ""))
                prepared.setdefault("artifact_refs", (bundle_view.get("artifact_context") or {}).get("artifact_refs") or [])
                prepared.setdefault("approval_context", bundle_view.get("approval_context") or {})
            except Exception:
                prepared.setdefault("context_bundle_error", "sanitize_failed")
        if tool_context:
            prepared.setdefault("tool_context", dict(tool_context or {}))
        return prepared

    @staticmethod
    def _update_context_bundle(context_bundle: Any | None, result: UnifiedToolResult) -> None:
        if context_bundle is None:
            return
        try:
            ContextManager().update_from_tool_result(context_bundle, result.to_dict())
        except Exception:
            return

    def _failure(
        self,
        tool_name: str,
        error_type: str,
        message: str,
        started_at: str,
        started: float,
        *,
        canonical_name: str = "",
        runtime_metadata: dict[str, Any] | None = None,
    ) -> UnifiedToolResult:
        finished_at = datetime.now().isoformat(timespec="seconds")
        trace_event(
            "tool.execute.blocked_or_failed",
            {"tool_name": tool_name, "canonical_tool_name": canonical_name or tool_name, "error_type": error_type, "message": message},
            level="ERROR",
        )
        return UnifiedToolResult(
            success=False,
            tool_name=tool_name,
            message=message,
            errors=[error_type],
            error_type=error_type,
            error_message=message,
            metadata={
                "canonical_tool_name": canonical_name or tool_name,
                "runtime_reliability": dict(runtime_metadata or {}),
            },
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=round((time.perf_counter() - started) * 1000.0, 3),
            retry_count=int((runtime_metadata or {}).get("retry_count") or 0),
            circuit_state=str((runtime_metadata or {}).get("circuit_state") or ""),
        )


def _ctx_path(context: dict[str, Any], key: str, default: str | Path = ".") -> str | Path:
    return context.get(key) or default


def _portfolio_state_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return portfolio_get_state_adapter(args, context)


def _portfolio_risk_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return portfolio_analyze_risk_adapter(args, context)


def _ranking_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return market_get_ranking_adapter(args, context)


def _stock_analysis_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return market_analyze_stock_adapter(args, context)


def _stock_news_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return evidence_search_news_adapter(args, context)


def _stock_rag_handler(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return evidence_search_rag_adapter(args, context)


def build_core_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="portfolio.get_state",
            display_name="Portfolio State",
            description=_description(
                "Read the current paper-trading account, cash, positions and orders.",
                "A user asks for current holdings, account state, or another analysis needs portfolio state.",
                "Generating market candidates, calculating target weights, modifying positions, or executing trades.",
                "user_id, output_dir, db_path.",
                "portfolio_state, account_summary and position_count.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=_portfolio_state_handler,
            supported_actions=["query", "analyze", "construct_recommendation"],
            supported_objects=["current_portfolio"],
            produced_outputs=["portfolio_state", "account_summary", "position_count"],
            legacy_names=["portfolio_state"],
        ),
        ToolDefinition(
            name="portfolio.get_account_summary",
            display_name="Portfolio Account Summary",
            description=_description(
                "Read the current paper-trading account summary and cash state.",
                "A user asks for account assets, cash, NAV, profit, drawdown or cash ratio.",
                "Changing account cash, committing cash flow, calculating rankings, or retrieving news.",
                "user_id, output_dir, db_path.",
                "account_summary, cash_state and account.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=portfolio_get_account_summary_adapter,
            supported_actions=["query", "analyze"],
            supported_objects=["paper_account", "current_portfolio"],
            produced_outputs=["account_summary", "cash_state", "account"],
            legacy_names=["portfolio_account_summary"],
        ),
        ToolDefinition(
            name="portfolio.get_positions",
            display_name="Portfolio Positions",
            description=_description(
                "Read current paper-trading positions and position weights.",
                "A user asks for holdings, position count, single-stock weight or current exposure.",
                "Changing positions, placing orders, calculating market ranking, or retrieving news.",
                "user_id, output_dir, db_path.",
                "positions, position_weights and position_count.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=portfolio_get_positions_adapter,
            supported_actions=["query", "analyze"],
            supported_objects=["positions", "current_portfolio"],
            produced_outputs=["positions", "position_weights", "position_count"],
            legacy_names=["portfolio_positions"],
        ),
        ToolDefinition(
            name="portfolio.get_orders",
            display_name="Portfolio Orders",
            description=_description(
                "Read current paper-trading order history snapshot.",
                "A user asks for paper orders, recent trades, order count or historical execution details.",
                "Committing new orders, changing positions, or calculating model rankings.",
                "user_id, output_dir, db_path.",
                "orders, order_count and latest_trade_date.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=portfolio_get_orders_adapter,
            supported_actions=["query", "analyze"],
            supported_objects=["orders", "paper_account"],
            produced_outputs=["orders", "order_count", "latest_trade_date"],
            legacy_names=["portfolio_orders"],
        ),
        ToolDefinition(
            name="portfolio.analyze_risk",
            display_name="Portfolio Risk",
            description=_description(
                "Read or compute current paper portfolio risk diagnostics.",
                "Risk review, target portfolio construction, or explanation needs current risk.",
                "Changing holdings, committing orders, or retrieving news.",
                "user_id, output_dir, db_path.",
                "current_risk, risk_factors and limitations.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=_portfolio_risk_handler,
            supported_actions=["analyze", "construct_recommendation", "explain"],
            supported_objects=["current_portfolio"],
            produced_outputs=["current_risk", "risk_factors", "limitations"],
            legacy_names=["portfolio_risk"],
        ),
        ToolDefinition(
            name="portfolio.compare_risk_before_after",
            display_name="Portfolio Risk Comparison",
            description=_description(
                "Compare before and after paper portfolio risk snapshots without committing changes.",
                "A proposal or report needs a read-only risk delta between two portfolio states.",
                "Committing portfolio changes, creating orders, or bypassing deterministic validators.",
                "user_id, before, after, output_dir, db_path.",
                "risk_before_after, delta, summary and limitations.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "before": {"type": "object"}, "after": {"type": "object"}}),
            output_schema=_result_schema(),
            execution_handler=portfolio_compare_risk_before_after_adapter,
            supported_actions=["analyze", "construct_recommendation", "explain"],
            supported_objects=["current_portfolio", "risk"],
            produced_outputs=["risk_before_after", "delta", "summary", "limitations"],
            legacy_names=["portfolio_risk_compare"],
        ),
        ToolDefinition(
            name="portfolio.design_target_portfolio",
            display_name="LLM Target Portfolio Design",
            description=_description(
                "Use the LLM after real portfolio, risk, profile and ranking data are available to design target portfolio parameters.",
                "The user asks for a more stable or otherwise optimized complete portfolio and expects the Agent to make the design decision.",
                "Creating orders, committing changes, inventing missing market data, or bypassing deterministic risk caps.",
                "current_portfolio, ranking, risk_report, user_profile, query and user_goal.",
                "target_design with target count, cash weight, candidate policy, allocation method, rationale, assumptions and source map.",
            ),
            input_schema=_schema(
                {
                    "current_portfolio": {"type": "object"},
                    "ranking": {"type": "object"},
                    "risk_report": {"type": "object"},
                    "user_profile": {"type": "object"},
                    "query": {"type": "string"},
                    "user_goal": {"type": "object"},
                    "construction_feedback": {"type": "object"},
                },
                required=["current_portfolio", "ranking"],
            ),
            output_schema=_result_schema(),
            execution_handler=design_target_portfolio_adapter,
            supported_actions=["construct", "recommend", "analyze"],
            supported_objects=["current_portfolio", "target_portfolio", "constraints"],
            produced_outputs=["target_design", "design_rationale", "assumptions", "not_executed"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["design_target_portfolio"],
        ),
        ToolDefinition(
            name="portfolio.construct_target_portfolio",
            display_name="Construct Target Portfolio",
            description=_description(
                "Construct and persist a complete read-only target paper portfolio from an LLM target design and deterministic constraints.",
                "The preceding LLM design task has produced target_design after reading current portfolio, risk, profile and ranking data.",
                "Redesigning the business recommendation, creating orders, changing positions, or bypassing approval.",
                "user_id, current_portfolio, ranking, risk_report, user_profile, target_design and optional explicit safety caps.",
                "target_portfolio, target_positions, target_portfolio_ref, current and target risk snapshots, limitations and not_executed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "current_portfolio": {"type": "object"},
                    "ranking": {"type": "object"},
                    "risk_report": {"type": "object"},
                    "user_profile": {"type": "object"},
                    "target_design": {"type": "object"},
                    "target_position_count": {"type": "integer"},
                    "target_cash_weight": {"type": "number"},
                    "candidate_policy": {"type": "string"},
                    "allocation_method": {"type": "string"},
                    "max_single_weight": {"type": "number"},
                    "max_industry_weight": {"type": "number"},
                },
                required=["current_portfolio", "ranking", "target_design"],
            ),
            output_schema=_result_schema(),
            execution_handler=construct_target_portfolio_adapter,
            supported_actions=["construct", "recommend", "compare"],
            supported_objects=["current_portfolio", "target_portfolio", "constraints"],
            produced_outputs=["target_portfolio", "target_positions", "target_portfolio_ref", "current_risk_snapshot", "target_risk_snapshot", "limitations", "not_executed"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["construct_target_portfolio"],
        ),
        ToolDefinition(
            name="portfolio.load_target_portfolio",
            display_name="Load Target Portfolio",
            description=_description(
                "Load a previously persisted structured target portfolio for the current conversation.",
                "A follow-up comparison references one prior target portfolio or provides an explicit artifact id.",
                "Guessing among multiple artifacts, generating a new target portfolio, or changing business state.",
                "user_id, conversation_id and optional artifact_id.",
                "target_portfolio, target_portfolio_ref, clarification details when absent or ambiguous.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "conversation_id": {"type": "string"}, "artifact_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=load_target_portfolio_adapter,
            supported_actions=["query", "compare"],
            supported_objects=["target_portfolio", "artifact"],
            produced_outputs=["target_portfolio", "target_portfolio_ref"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["load_target_portfolio"],
        ),
        ToolDefinition(
            name="portfolio.compare_portfolios",
            display_name="Compare Portfolios",
            description=_description(
                "Compare current and target paper portfolios deterministically without creating orders.",
                "Both current_portfolio and target_portfolio are available as structured task outputs.",
                "Comparing only one portfolio, regenerating recommendations, or committing changes.",
                "current_portfolio and target_portfolio.",
                "portfolio_comparison, current_vs_target, added/removed/increased/decreased holdings, cash difference and risk before/after.",
            ),
            input_schema=_schema({"current_portfolio": {"type": "object"}, "target_portfolio": {"type": "object"}}, required=["current_portfolio", "target_portfolio"]),
            output_schema=_result_schema(),
            execution_handler=compare_portfolios_adapter,
            supported_actions=["compare", "analyze", "explain"],
            supported_objects=["current_portfolio", "target_portfolio"],
            produced_outputs=["portfolio_comparison", "current_vs_target", "added_stocks", "removed_stocks", "increased_stocks", "decreased_stocks", "cash_difference", "risk_before_after", "not_executed"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["compare_portfolios"],
        ),
        ToolDefinition(
            name="market.get_ranking",
            display_name="Market Ranking",
            description=_description(
                "Read the latest local model ranking or a specific stock row.",
                "Market evidence, TopK display, stock candidate generation or target portfolio construction.",
                "Portfolio write operations, account state, or broker execution.",
                "stock_code, top_k, output_dir.",
                "candidate_stocks, market_evidence, reasons and limitations.",
            ),
            input_schema=_schema({"stock_code": {"type": "string"}, "top_k": {"type": "integer"}, "model_name": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=_ranking_handler,
            supported_actions=["query", "construct_recommendation", "explain"],
            supported_objects=["market_evidence", "candidate_stocks"],
            produced_outputs=["candidate_stocks", "market_evidence", "reasons", "limitations"],
            legacy_names=["ranking"],
        ),
        ToolDefinition(
            name="market.analyze_stock",
            display_name="Stock Analysis",
            description=_description(
                "Analyze one explicit stock using ranking, AI adjustment, news, RAG and user suitability.",
                "A task has an explicit stock code or receives codes from a previous ranking task.",
                "Open-ended portfolio construction without a stock code, or write operations.",
                "user_id, stock_code, top_k, output_dir, db_path.",
                "stock_analysis, evidence, reasons and limitations.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "stock_code": {"type": "string"}, "top_k": {"type": "integer"}}, required=["stock_code"]),
            output_schema=_result_schema(),
            execution_handler=_stock_analysis_handler,
            supported_actions=["analyze", "explain"],
            supported_objects=["stock", "market_evidence"],
            produced_outputs=["stock_analysis", "market_evidence", "evidence", "reasons", "limitations"],
            legacy_names=["stock_analysis"],
        ),
        ToolDefinition(
            name="market.lookup_stock",
            display_name="Stock Lookup",
            description=_description(
                "Resolve a stock code or name against the latest local ranking and AI recommendation rows.",
                "A task needs a stock identifier, stock name, local rank, or row-level market evidence before analysis.",
                "News retrieval, portfolio writes, or committing paper-trading changes.",
                "user_id, stock_query or stock_code, output_dir.",
                "stock_lookup, market_evidence, sources and limitations.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "stock_query": {"type": "string"}, "stock_code": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=market_lookup_stock_adapter,
            supported_actions=["query", "analyze", "explain"],
            supported_objects=["stock", "market_evidence"],
            produced_outputs=["stock_lookup", "market_evidence", "evidence", "reasons", "limitations"],
            legacy_names=["stock_lookup", "classic_stock_score"],
        ),
        ToolDefinition(
            name="market.compare_stocks",
            display_name="Compare Stocks",
            description=_description(
                "Compare multiple explicit stocks using existing local ranking and AI adjustment evidence.",
                "A user asks to compare candidates or a plan needs read-only stock-to-stock context.",
                "Selecting a trade to commit, modifying paper holdings, or retrieving remote evidence.",
                "user_id, stock_codes, top_k, output_dir, db_path.",
                "comparison records, summary, sources and limitations.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "stock_codes": {"type": "array"}, "stock_code": {"type": "string"}, "top_k": {"type": "integer"}}),
            output_schema=_result_schema(),
            execution_handler=market_compare_stocks_adapter,
            supported_actions=["compare", "analyze", "explain"],
            supported_objects=["stock", "market_evidence"],
            produced_outputs=["stock_comparison", "market_evidence", "evidence", "reasons", "limitations"],
            legacy_names=[],
        ),
        ToolDefinition(
            name="market.get_signal_summary",
            display_name="Signal Summary",
            description=_description(
                "Read the classic local signal table that merges raw ranking with stored AI adjustment results.",
                "The UI or Agent needs the same read-only signal summary as the classic home ranking table.",
                "Generating new recommendations, retrieving news, or changing portfolio state.",
                "user_id, sort_by, output_dir.",
                "signal summary records, sources, as_of_date and not_executed marker.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}, "sort_by": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=market_signal_summary_adapter,
            supported_actions=["query", "explain"],
            supported_objects=["market_evidence", "candidate_stocks"],
            produced_outputs=["candidate_stocks", "market_evidence", "signal_summary", "reasons", "limitations"],
            legacy_names=["classic_ranking"],
        ),
        ToolDefinition(
            name="evidence.search_news",
            display_name="News Evidence Search",
            description=_description(
                "Read locally mapped news events for one explicit stock.",
                "A stock-specific news or event evidence task needs local news records.",
                "Ranking, portfolio writes, or fetching remote news.",
                "stock_code, as_of_date, limit, db_path.",
                "news_events, evidence records, sources, reasons and limitations.",
            ),
            input_schema=_schema({"stock_code": {"type": "string"}, "as_of_date": {"type": "string"}, "limit": {"type": "integer"}, "top_k": {"type": "integer"}}),
            output_schema=_result_schema(),
            execution_handler=_stock_news_handler,
            supported_actions=["query", "retrieve_evidence", "explain"],
            supported_objects=["stock", "news_evidence", "market_evidence"],
            produced_outputs=["news_events", "evidence", "market_evidence", "sources", "reasons", "limitations"],
            legacy_names=["stock_news", "news_search"],
        ),
        ToolDefinition(
            name="evidence.search_rag",
            display_name="RAG Evidence Search",
            description=_description(
                "Read local RAG chunks for one explicit stock.",
                "A stock-specific evidence retrieval task needs local RAG contexts.",
                "Ranking, remote search, portfolio writes, or committing plans.",
                "stock_code, query, top_k, output_dir.",
                "rag_contexts, evidence records, sources, market_evidence and limitations.",
            ),
            input_schema=_schema({"stock_code": {"type": "string"}, "query": {"type": "string"}, "top_k": {"type": "integer"}}),
            output_schema=_result_schema(),
            execution_handler=_stock_rag_handler,
            supported_actions=["query", "retrieve_evidence", "explain"],
            supported_objects=["stock", "rag_evidence", "market_evidence"],
            produced_outputs=["rag_contexts", "evidence", "market_evidence", "sources", "limitations"],
            legacy_names=["stock_rag", "rag_search"],
        ),
        ToolDefinition(
            name="evidence.get_stock_evidence",
            display_name="Stock Evidence",
            description=_description(
                "Collect read-only news and RAG evidence for one explicit stock using existing local stores.",
                "A task needs a unified evidence packet for one stock.",
                "Ranking, portfolio writes, broker execution, or changing RAG/news stores.",
                "stock_code, query, as_of_date, top_k, output_dir, db_path.",
                "unified evidence records, sources, summary and limitations.",
            ),
            input_schema=_schema({"stock_code": {"type": "string"}, "query": {"type": "string"}, "as_of_date": {"type": "string"}, "top_k": {"type": "integer"}}),
            output_schema=_result_schema(),
            execution_handler=evidence_get_stock_evidence_adapter,
            supported_actions=["query", "retrieve_evidence", "explain"],
            supported_objects=["stock", "market_evidence"],
            produced_outputs=["evidence", "market_evidence", "sources", "reasons", "limitations"],
            legacy_names=[],
        ),
        ToolDefinition(
            name="evidence.get_market_evidence",
            display_name="Market Evidence",
            description=_description(
                "Collect read-only evidence for multiple explicit stocks or a market-evidence query.",
                "A task needs combined evidence for several local stock candidates.",
                "Ranking generation, portfolio writes, broker execution, or remote write tools.",
                "query, stock_codes, as_of_date, top_k, output_dir, db_path.",
                "market evidence records, sources, summary and limitations.",
            ),
            input_schema=_schema({"query": {"type": "string"}, "stock_codes": {"type": "array"}, "stock_code": {"type": "string"}, "as_of_date": {"type": "string"}, "top_k": {"type": "integer"}}),
            output_schema=_result_schema(),
            execution_handler=evidence_get_market_evidence_adapter,
            supported_actions=["query", "retrieve_evidence", "explain"],
            supported_objects=["market_evidence"],
            produced_outputs=["evidence", "market_evidence", "sources", "reasons", "limitations"],
            legacy_names=[],
        ),
        ToolDefinition(
            name="evidence.mcp_readonly_evidence",
            display_name="MCP Read-only Evidence",
            description=_description(
                "Invoke one allowlisted read-only MCP evidence tool and normalize its evidence fields.",
                "An external MCP evidence tool has been selected for market or risk context.",
                "Any write, destructive, broker, paper-trading, strategy, cash or database mutation tool.",
                "mcp_tool_name and arguments.",
                "MCP evidence records, source metadata, warnings and read-only audit markers.",
                side_effects="None; read-only MCP evidence bridge, write tools are blocked before execution.",
            ),
            input_schema=_schema({"mcp_tool_name": {"type": "string"}, "tool_name": {"type": "string"}, "arguments": {"type": "object"}}, required=["mcp_tool_name"]),
            output_schema=_result_schema(),
            execution_handler=evidence_mcp_readonly_adapter,
            supported_actions=["query", "retrieve_evidence"],
            supported_objects=["mcp_evidence", "market_evidence"],
            produced_outputs=["market_evidence", "evidence", "mcp_sources", "sources", "limitations"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["mcp_market_risk_summary"],
        ),
        ToolDefinition(
            name="system.scheduler_status",
            display_name="Scheduler Status",
            description=_description(
                "Read local scheduler status and recent update log tail.",
                "A user asks about background update or scheduled job status.",
                "Running an update, changing schedules, or writing data.",
                "output root.",
                "scheduler_status.",
            ),
            input_schema=_schema(),
            output_schema=_result_schema(),
            execution_handler=scheduler_status_adapter,
            supported_actions=["system_control", "query"],
            supported_objects=["scheduler"],
            produced_outputs=["scheduler_status"],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[AGENT_MAIN],
            permission_scope=OP_SYSTEM,
            legacy_names=["scheduler_status"],
        ),
        ToolDefinition(
            name="report.list_latest",
            display_name="Latest Reports",
            description=_description(
                "List latest generated local project reports.",
                "A user asks to inspect already generated reports.",
                "Generating new reports or changing portfolio state.",
                "output_dir.",
                "report_summary.",
            ),
            input_schema=_schema(),
            output_schema=_result_schema(),
            execution_handler=report_list_latest_adapter,
            supported_actions=["query", "explain"],
            supported_objects=["report"],
            produced_outputs=["report_summary"],
            legacy_names=["report", "report_latest"],
        ),
        ToolDefinition(
            name="memory.search",
            display_name="Memory Search",
            description=_description(
                "Read sanitized Agent memory records for the current user.",
                "A task needs user preference, prior decision, evidence, or portfolio memory context.",
                "Writing memory, committing portfolio changes, approval, strategy updates, or storing new user facts.",
                "user_id, query, memory_types, topics, stock_codes, limit, output_dir.",
                "sanitized memory items, score parts and read-only policy.",
                side_effects="None; read-only memory search.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "query": {"type": "string"},
                    "memory_types": {"type": "array"},
                    "topics": {"type": "array"},
                    "stock_codes": {"type": "array"},
                    "limit": {"type": "integer"},
                }
            ),
            output_schema=_result_schema(),
            execution_handler=memory_search_adapter,
            supported_actions=["query", "retrieve_context"],
            supported_objects=["memory", "user_context"],
            produced_outputs=["memory_context", "user_preferences", "evidence"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=[],
        ),
        ToolDefinition(
            name="memory.get_summary",
            display_name="Memory Summary",
            description=_description(
                "Read Agent memory store health and safe aggregate counts.",
                "The UI, system monitor or Agent needs memory-store status.",
                "Writing memory, committing business state, or exposing secrets.",
                "user_id, output_dir.",
                "memory store status, counts and latest memory type summary.",
                side_effects="None; read-only memory summary.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=memory_get_summary_adapter,
            supported_actions=["query", "system_control"],
            supported_objects=["memory", "system"],
            produced_outputs=["memory_health", "memory_context"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=[],
        ),
        ToolDefinition(
            name="user.profile.get",
            display_name="User Profile",
            description=_description(
                "Read the user's risk profile, investment goal, constraints and trading permissions.",
                "A task needs profile constraints or user suitability before analysis or proposal preview.",
                "Saving profile settings, changing preferences, or modifying paper-trading state.",
                "user_id, output_dir, db_path.",
                "user_profile, risk_assessment, investment_goal and constraints.",
            ),
            input_schema=_schema({"user_id": {"type": "string"}}),
            output_schema=_result_schema(),
            execution_handler=user_profile_get_adapter,
            supported_actions=["query", "analyze"],
            supported_objects=["user_profile", "constraints"],
            produced_outputs=["user_profile", "risk_assessment", "investment_goal", "constraints"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["user_profile"],
        ),
        ToolDefinition(
            name="sandbox.python_analysis",
            display_name="Python Sandbox Analysis",
            description=_description(
                "Run limited read-only Python analysis over an explicit task snapshot.",
                "A task needs deterministic calculations over already provided structured data.",
                "Reading files, writing files, accessing secrets, mutating portfolio data, or running open-ended code.",
                "code, snapshot, snapshot_id, timeout_seconds, max_output_chars.",
                "sandbox result, stdout summary, warnings and security status.",
                side_effects="None; restricted read-only sandbox, no business-state writes.",
            ),
            input_schema=_schema(
                {
                    "code": {"type": "string"},
                    "snapshot": {"type": "object"},
                    "snapshot_id": {"type": "string"},
                    "timeout_seconds": {"type": "number"},
                    "max_output_chars": {"type": "integer"},
                },
                required=["code"],
            ),
            output_schema=_result_schema(),
            execution_handler=python_sandbox_analysis_adapter,
            supported_actions=["analyze", "calculate"],
            supported_objects=["snapshot", "system"],
            produced_outputs=["sandbox_result", "calculation", "warnings"],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[AGENT_MAIN],
            permission_scope=OP_SYSTEM,
            runtime_policy={"max_attempts": 1, "tool_timeout_seconds": 10},
            legacy_names=["python_sandbox_analysis"],
        ),
        ToolDefinition(
            name="mcp.readonly.invoke",
            display_name="MCP Read-only Invoke",
            description=_description(
                "Invoke one allowlisted read-only MCP evidence tool through the v2 ToolExecutor.",
                "A selected MCP tool has been discovered as read-only and is needed as external evidence.",
                "Any write, destructive, broker, paper-trading, strategy, cash or database mutation tool.",
                "mcp_tool_name and arguments.",
                "MCP evidence payload, source metadata, warnings and read-only audit markers.",
                side_effects="None; read-only MCP bridge, write tools are blocked before execution.",
            ),
            input_schema=_schema(
                {
                    "mcp_tool_name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                required=["mcp_tool_name"],
            ),
            output_schema=_result_schema(),
            execution_handler=evidence_mcp_readonly_adapter,
            supported_actions=["query", "retrieve_evidence"],
            supported_objects=["mcp_evidence", "market_evidence"],
            produced_outputs=["market_evidence", "evidence", "mcp_sources", "limitations"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["mcp_tool"],
        ),
        ToolDefinition(
            name="portfolio.recommend_position",
            display_name="Portfolio Position Recommendation",
            description=_description(
                "Generate a read-only target weight recommendation for one paper-trading stock candidate.",
                "A user asks how large a paper position should be, or a proposal preview needs target-weight evidence.",
                "Creating confirmation plans, modifying paper positions, or executing paper orders.",
                "user_id, stock_code, requested_weight, top_k, output_dir, db_path.",
                "candidate_stocks, target_weights, current_vs_target, risk_notes, assumptions and not_executed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "top_k": {"type": "integer"},
                },
                required=["stock_code"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_recommend_position_adapter,
            supported_actions=["recommend_position", "construct_recommendation"],
            supported_objects=["current_portfolio", "stock"],
            produced_outputs=["candidate_stocks", "target_weights", "current_vs_target", "risk_notes", "assumptions", "not_executed"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["position_recommendation"],
        ),
        ToolDefinition(
            name="portfolio.recommend_replacement",
            display_name="Portfolio Replacement Recommendation",
            description=_description(
                "Rank current paper positions that could be reduced to fund a candidate stock.",
                "A user asks which existing paper holdings are weaker, risky, overweight, or replaceable.",
                "Changing holdings, creating orders, or committing a replacement.",
                "user_id, stock_code, requested_weight, limit, output_dir, db_path.",
                "source_stock, replacement_candidates, reason, score_comparison, risk_comparison and not_executed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "limit": {"type": "integer"},
                },
                required=["stock_code"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_recommend_replacement_adapter,
            supported_actions=["recommend_replacement", "construct_recommendation"],
            supported_objects=["current_portfolio", "stock"],
            produced_outputs=["source_stock", "replacement_candidates", "score_comparison", "risk_comparison", "not_executed"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
            legacy_names=["replacement_recommendation"],
        ),
        ToolDefinition(
            name="portfolio.preview_manual_change",
            display_name="Portfolio Manual Change Preview",
            description=_description(
                "Create a confirmation-required one-time paper-position change proposal.",
                "A user explicitly asks to add, reduce, sell, or target a stock weight in the paper portfolio.",
                "Committing the paper order, changing long-term strategy, or bypassing user confirmation.",
                "user_id, stock_code, requested_weight, position_adjustment_ratio, requested_quantity, cash_weight, target_position_count, query.",
                "operation_preview, order_preview, cash_impact, risk_impact, confirmation_plan and not_committed.",
                "Creates a pending confirmation plan only; no paper position is written.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "position_adjustment_ratio": {"type": "number"},
                    "requested_quantity": {"type": "number"},
                    "cash_weight": {"type": "number"},
                    "target_position_count": {"type": "integer"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_preview_manual_change_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["current_portfolio", "paper_account"],
            produced_outputs=["operation_preview", "order_preview", "cash_impact", "risk_impact", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["manual_position_operation_tool"],
        ),
        ToolDefinition(
            name="portfolio.preview_rebalance",
            display_name="Portfolio Rebalance Preview",
            description=_description(
                "Create a confirmation-required paper rebalance/add-position proposal from a candidate stock.",
                "A user asks to add a stock or create a rebalance preview before any paper-trading write.",
                "Committing orders, changing long-term strategy, or changing one-lot/cash allocation rules.",
                "user_id, stock_code, requested_weight, top_k, output_dir, db_path.",
                "current_positions, target_positions, orders_preview, cash_before_after, one_lot_check, confirmation_plan.",
                "Creates a pending confirmation plan only; no paper position is written.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "top_k": {"type": "integer"},
                },
                required=["stock_code"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_preview_rebalance_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["current_portfolio", "paper_account"],
            produced_outputs=["operation_preview", "target_portfolio", "orders_preview", "cash_before_after", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["rebalance_plan"],
        ),
        ToolDefinition(
            name="portfolio.preview_adjust_position",
            display_name="Portfolio Adjust Position Preview",
            description=_description(
                "Create a confirmation-required preview for adjusting an existing paper position.",
                "A user asks to reduce, sell, increase, or target the weight of an existing paper holding.",
                "Committing orders, changing long-term strategy, or bypassing one-lot validation.",
                "user_id, stock_code, requested_weight, position_adjustment_ratio, requested_quantity, top_k.",
                "orders_preview, cash_before_after, one_lot_check, risk_before_after, confirmation_plan and not_committed.",
                "Creates a pending confirmation plan only; no paper position is written.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "position_adjustment_ratio": {"type": "number"},
                    "requested_quantity": {"type": "number"},
                    "top_k": {"type": "integer"},
                },
                required=["stock_code"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_preview_adjust_position_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["current_portfolio", "paper_account"],
            produced_outputs=["operation_preview", "orders_preview", "cash_before_after", "risk_before_after", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["adjust_position"],
        ),
        ToolDefinition(
            name="portfolio.preview_paper_trade",
            display_name="Portfolio Paper Trade Preview",
            description=_description(
                "Convert a candidate stock and target weight into a confirmation-required paper-order preview.",
                "A user asks for an executable-looking paper-trade preview, but has not confirmed execution.",
                "Committing orders, broker trading, or changing long-term strategy.",
                "user_id, stock_code, requested_weight, top_k, output_dir, db_path.",
                "order_preview, cash_impact, risk_impact, confirmation_plan and not_committed.",
                "Creates a pending confirmation plan only; no paper position is written.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "stock_code": {"type": "string"},
                    "requested_weight": {"type": "number"},
                    "top_k": {"type": "integer"},
                },
                required=["stock_code"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_preview_paper_trade_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["current_portfolio", "paper_account"],
            produced_outputs=["operation_preview", "order_preview", "cash_impact", "risk_impact", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["paper_trade_preview"],
        ),
        ToolDefinition(
            name="portfolio.commit_paper_trade",
            display_name="Portfolio Paper Trade Commit",
            description=_description(
                "Commit a confirmed paper-trading plan after token, plan hash, state and trading-day revalidation.",
                "A pending execute_add_stock or execute_adjust_position plan has a valid user confirmation token.",
                "Previewing paper trades, creating new proposals, or any unapproved write.",
                "user_id, plan_id, confirmation_token, output_dir, db_path.",
                "revalidation_result, commit_result, audit_record.",
                "Writes paper account state only after approval, revalidation and idempotency checks.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(),
            execution_handler=portfolio_commit_paper_trade_adapter,
            supported_actions=["execute_confirmed_plan", "commit_write_operation"],
            supported_objects=["current_portfolio", "paper_account"],
            produced_outputs=["revalidation_result", "commit_result", "audit_record"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            legacy_names=["paper_trade_execute", "paper_trading_execution_tool"],
        ),
        ToolDefinition(
            name="strategy.get_context",
            display_name="Strategy Conversation Context",
            description=_description(
                "Read the scoped account, positions, runtime strategy, constraints, related conversation and active proposal context.",
                "The LLM is designing or revising a long-term paper-strategy proposal.",
                "Generating strategy meaning, changing formal strategy state, or changing positions.",
                "user_id, account_id and conversation_id.",
                "strategy_conversation_context.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                }
            ),
            output_schema=_result_schema(["strategy_conversation_context"]),
            execution_handler=strategy_get_context_adapter,
            supported_actions=["query"],
            supported_objects=["strategy", "paper_account", "conversation"],
            produced_outputs=["strategy_conversation_context"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
        ),
        ToolDefinition(
            name="strategy.get_active_proposal",
            display_name="Active Strategy Proposal",
            description=_description(
                "Read the active versioned strategy proposal in the exact user, account and conversation scope.",
                "The LLM needs to continue or inspect an existing strategy discussion.",
                "Cross-user access, interpreting feedback, implementation, or formal writes.",
                "user_id, account_id and conversation_id.",
                "proposal and proposal version history.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                }
            ),
            output_schema=_result_schema(["proposal", "versions"]),
            execution_handler=strategy_get_active_proposal_adapter,
            supported_actions=["query"],
            supported_objects=["strategy_proposal"],
            produced_outputs=["strategy_proposal", "strategy_proposal_versions"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
        ),
        ToolDefinition(
            name="strategy.get_audit_trace",
            display_name="Strategy Audit Trace",
            description=_description(
                "Reconstruct the complete long-term strategy lifecycle from stable proposal, implementation, plan, commit, binding, run or conversation identifiers.",
                "The user or developer needs a read-only audit view of discussion, implementation, approval, registration, binding and actual paper execution.",
                "Creating strategy semantics, approving a plan, changing a binding, or changing positions.",
                "user_id plus any known lifecycle identifiers.",
                "redacted strategy_audit_trace without confirmation secrets.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "proposal_id": {"type": "string"},
                    "implementation_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "commit_id": {"type": "string"},
                    "binding_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                },
                required=["user_id"],
            ),
            output_schema=_result_schema(["strategy_audit_trace"]),
            execution_handler=strategy_get_audit_trace_adapter,
            supported_actions=["query_audit"],
            supported_objects=[
                "strategy_proposal",
                "strategy_implementation",
                "strategy_plan",
                "strategy_binding",
                "paper_execution",
            ],
            produced_outputs=["strategy_audit_trace"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_MAIN, AGENT_READ],
            permission_scope=OP_READ,
        ),
        ToolDefinition(
            name="strategy.save_proposal_draft",
            display_name="Save Strategy Proposal Draft",
            description=_description(
                "Persist the exact LLM-authored strategy proposal or discussion action as a versioned draft without reinterpreting free text.",
                "The LLM has already used the full conversation context to choose continue, save, ask-before-implementation, prepare-implementation, or safe LLM-failure fallback.",
                "Generating strategy semantics, writing code, registering or activating a strategy, or changing positions.",
                "scoped IDs, conversation_action, proposal_json, feedback and version summary.",
                "versioned proposal draft and implementation_requested marker.",
                "Writes conversation draft metadata only; creates no confirmation plan and changes no formal strategy or portfolio state.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "conversation_action": {
                        "type": "string",
                        "enum": [
                            "continue_discussion",
                            "save_proposal",
                            "ask_implementation",
                            "prepare_implementation",
                            "llm_unavailable",
                        ],
                    },
                    "proposal_id": {"type": "string"},
                    "proposal_json": {"type": "object"},
                    "original_request": {"type": "string"},
                    "user_feedback": {"type": "string"},
                    "change_summary": {"type": "string"},
                    "base_strategy_id": {"type": "string"},
                    "base_strategy_version": {"type": "string"},
                    "source_run_id": {"type": "string"},
                },
                required=["conversation_action"],
            ),
            output_schema=_result_schema(["conversation_action"]),
            execution_handler=strategy_save_proposal_draft_adapter,
            supported_actions=["save_draft", "continue_discussion"],
            supported_objects=["strategy_proposal"],
            produced_outputs=[
                "strategy_proposal",
                "strategy_proposal_version",
                "implementation_requested",
            ],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN],
            permission_scope=OP_PROPOSAL,
            requires_approval=False,
        ),
        ToolDefinition(
            name="strategy.prepare_implementation",
            display_name="Prepare Isolated Strategy Implementation",
            description=_description(
                "Lock one exact Proposal version and generate configuration, composition, or plugin artifacts in the isolated strategy-drafts directory.",
                "The LLM has explicitly chosen prepare_implementation for an existing scoped Proposal version.",
                "Free-text reinterpretation, formal project writes, Registry changes, Binding changes, or position changes.",
                "proposal_id, proposal_version, user_id, account_id, conversation_id and run_id.",
                "isolated implementation artifacts and content hashes.",
                "Writes only runtime/strategy_drafts; no formal state is changed and no approval plan is created.",
            ),
            input_schema=_schema(
                {
                    "proposal_id": {"type": "string"},
                    "proposal_version": {"type": "integer"},
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                required=[
                    "proposal_id",
                    "proposal_version",
                    "user_id",
                    "account_id",
                    "conversation_id",
                    "run_id",
                ],
            ),
            output_schema=_result_schema(
                ["implementation_id", "implementation_hash"]
            ),
            execution_handler=strategy_prepare_implementation_adapter,
            supported_actions=["prepare_isolated_implementation"],
            supported_objects=["strategy_proposal", "strategy_implementation"],
            produced_outputs=[
                "strategy_implementation",
                "artifact_manifest",
                "implementation_preview",
            ],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN],
            permission_scope=OP_PROPOSAL,
            requires_approval=False,
        ),
        ToolDefinition(
            name="strategy.create_apply_plan",
            display_name="Create Strategy Apply Plan",
            description=_description(
                "Create a hash-bound confirmation plan for applying one validated isolated implementation and registering it as disabled.",
                "A validated implementation preview is ready for explicit formal-application confirmation.",
                "Applying files, registering without confirmation, activating a strategy, or changing positions.",
                "implementation_id and scoped user/account/conversation/run IDs.",
                "apply_strategy_implementation confirmation plan.",
                "Creates a pending confirmation plan only; formal project and Registry remain unchanged.",
            ),
            input_schema=_schema(
                {
                    "implementation_id": {"type": "string"},
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                required=[
                    "implementation_id",
                    "user_id",
                    "account_id",
                    "conversation_id",
                    "run_id",
                ],
            ),
            output_schema=_result_schema(["plan_id"]),
            execution_handler=strategy_create_apply_plan_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["strategy_implementation", "strategy_registry"],
            produced_outputs=[
                "implementation_preview",
                "confirmation_request",
                "not_committed",
            ],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            requires_approval=False,
        ),
        ToolDefinition(
            name="strategy.apply.commit",
            display_name="Commit Strategy Implementation",
            description=_description(
                "Revalidate every Proposal, artifact, report and formal-baseline hash, then transactionally add a new strategy version and register it disabled.",
                "WriteGateway dispatches a confirmed apply_strategy_implementation plan.",
                "Unconfirmed calls, activation, position changes, or overwriting an existing strategy file.",
                "user_id, plan_id and confirmation_token.",
                "commit, registered-disabled manifest and audit identifiers.",
                "Adds only a new formal strategy version after approval; rolls back file and Registry on failure.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(["commit_id", "strategy_manifest"]),
            execution_handler=strategy_apply_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["strategy_implementation", "strategy_registry"],
            produced_outputs=[
                "revalidation_result",
                "commit_result",
                "audit_record",
            ],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
        ),
        ToolDefinition(
            name="strategy.create_activation_plan",
            display_name="Create Account Strategy Activation Plan",
            description=_description(
                "Create an account-scoped confirmation plan for activating a registered-disabled strategy version from an effective date.",
                "A registered strategy version is ready for a separate account activation decision.",
                "Global Registry enablement, immediate position changes, or unconfirmed activation.",
                "user/account scope, strategy ID/version, effective date and conversation/run IDs.",
                "activation preview and confirmation request.",
                "Creates a pending plan only; Binding and positions remain unchanged.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "strategy_id": {"type": "string"},
                    "strategy_version": {"type": "string"},
                    "effective_from": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                required=[
                    "user_id",
                    "account_id",
                    "strategy_id",
                    "strategy_version",
                ],
            ),
            output_schema=_result_schema(["plan_id"]),
            execution_handler=strategy_create_activation_plan_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["strategy_binding", "paper_account"],
            produced_outputs=["activation_preview", "confirmation_request"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
        ),
        ToolDefinition(
            name="strategy.create_binding_rollback_plan",
            display_name="Create Strategy Binding Rollback Plan",
            description=_description(
                "Create a confirmation plan that restores the previous account strategy as a new binding history event.",
                "An account has a previous binding and the user asks to roll back.",
                "Deleting binding history, global Registry changes, or position rollback.",
                "user/account scope and conversation/run IDs.",
                "rollback preview and confirmation request.",
                "Creates a pending plan only and preserves all binding history.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                required=["user_id", "account_id"],
            ),
            output_schema=_result_schema(["plan_id"]),
            execution_handler=strategy_create_binding_rollback_plan_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["strategy_binding"],
            produced_outputs=["rollback_preview", "confirmation_request"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
        ),
        ToolDefinition(
            name="strategy.binding.commit",
            display_name="Commit Account Strategy Binding",
            description=_description(
                "Commit a confirmed account-scoped strategy activation or rollback after Binding and config-hash revalidation.",
                "WriteGateway dispatches an activation/rollback plan with a valid confirmation.",
                "Global strategy enablement or current position changes.",
                "user_id, plan_id and confirmation_token.",
                "binding record, commit and audit identifiers.",
                "Writes one account Binding history event; creates no orders and changes no positions.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(["binding", "commit_id"]),
            execution_handler=strategy_binding_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["strategy_binding", "paper_account"],
            produced_outputs=[
                "revalidation_result",
                "commit_result",
                "audit_record",
            ],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
        ),
        ToolDefinition(
            name="strategy.preview_current_position_change",
            display_name="Preview Current Strategy Position Change",
            description=_description(
                "Generate a full current-position target, order, fee, cash and risk preview from the effective account Binding.",
                "The user explicitly asks to apply the newly enabled strategy to current paper positions now.",
                "Changing positions, cash, orders or NAV before a separate portfolio confirmation.",
                "user/account scope, optional recommendations, trade date and conversation/run IDs.",
                "TargetPortfolio, order preview, fees, risk delta and a portfolio-specific confirmation request.",
                "Creates a pending portfolio plan only; strategy registration and Binding remain unchanged.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "account_id": {"type": "string"},
                    "recommendations": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                    "trade_date": {"type": "string"},
                    "conversation_id": {"type": "string"},
                    "run_id": {"type": "string"},
                },
                required=["user_id", "account_id"],
            ),
            output_schema=_result_schema(
                ["plan_id", "target_portfolio", "orders_preview"]
            ),
            execution_handler=strategy_preview_position_change_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=[
                "strategy_binding",
                "paper_account",
                "target_portfolio",
            ],
            produced_outputs=[
                "target_portfolio",
                "order_preview",
                "risk_impact",
                "confirmation_request",
            ],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
        ),
        ToolDefinition(
            name="strategy.position.commit",
            display_name="Commit Current Strategy Position Change",
            description=_description(
                "Revalidate account state and Binding config hash, then run the original paper pipeline for a confirmed current-position strategy change.",
                "WriteGateway dispatches a valid execute_strategy_position_change plan.",
                "Unconfirmed execution, strategy registration or Binding mutation.",
                "user_id, plan_id and confirmation_token.",
                "paper orders, strategy metadata, snapshots and commit identifiers.",
                "Writes only after portfolio-specific confirmation and preserves before/after history.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(["commit_id", "order_ids"]),
            execution_handler=strategy_position_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=[
                "paper_account",
                "paper_position",
                "paper_order",
            ],
            produced_outputs=[
                "revalidation_result",
                "commit_result",
                "audit_record",
            ],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
        ),
        ToolDefinition(
            name="strategy.builder.preview",
            display_name="Strategy Builder Preview",
            description=_description(
                "Create a confirmation-required preview for registering a long-term paper strategy configuration.",
                "A user asks to change future paper-trading strategy rules or register a strategy variant.",
                "Committing strategy registration, enabling strategies, executing paper orders, or bypassing confirmation.",
                "user_id, requirement, parameters, output_dir, db_path.",
                "operation_preview, strategy_manifest, validation_result, confirmation_request and not_committed.",
                "Creates a pending confirmation plan only; no strategy registry state is changed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "requirement": {"type": "string"},
                    "parameters": {"type": "object"},
                },
                required=["requirement"],
            ),
            output_schema=_result_schema(),
            execution_handler=strategy_builder_preview_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["strategy"],
            produced_outputs=["operation_preview", "strategy_manifest", "validation_result", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["strategy_builder_tool"],
        ),
        ToolDefinition(
            name="strategy.management.preview",
            display_name="Strategy Management Preview",
            description=_description(
                "List strategies or create confirmation-required previews for enable, switch or disable actions.",
                "A user asks to inspect or manage paper-trading strategy versions before any protected write.",
                "Committing strategy changes, executing paper orders, or bypassing confirmation.",
                "user_id, action, strategy_id, strategy_version, output_dir, db_path.",
                "strategies, operation_preview, strategy_manifest, confirmation_request and not_committed.",
                "List action is read-only; mutating actions create a pending confirmation plan only.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "action": {"type": "string"},
                    "strategy_id": {"type": "string"},
                    "strategy_version": {"type": "string"},
                },
                required=["action"],
            ),
            output_schema=_result_schema(),
            execution_handler=strategy_management_preview_adapter,
            supported_actions=["query", "preview_write_operation"],
            supported_objects=["strategy"],
            produced_outputs=["strategies", "operation_preview", "strategy_manifest", "confirmation_request", "not_committed"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["strategy_management_tool"],
        ),
        ToolDefinition(
            name="strategy.disable.preview",
            display_name="Strategy Disable Preview",
            description=_description(
                "Create a confirmation proposal for disabling a paper-trading strategy.",
                "A user requests disabling a strategy version and no write should happen before confirmation.",
                "Registering, enabling, or executing paper orders.",
                "user_id, strategy_id, strategy_version, output_dir, db_path.",
                "operation_preview, confirmation_request, risk_impact.",
                "Creates an approval proposal only; no business state is changed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "strategy_id": {"type": "string"},
                    "strategy_version": {"type": "string"},
                },
                required=["strategy_id"],
            ),
            output_schema=_result_schema(),
            execution_handler=strategy_disable_preview_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["strategy"],
            produced_outputs=["operation_preview", "confirmation_request", "risk_impact"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["strategy_disable_preview"],
        ),
        ToolDefinition(
            name="strategy.disable.commit",
            display_name="Strategy Disable Commit",
            description=_description(
                "Commit a confirmed strategy disable plan after revalidation.",
                "A pending disable_strategy plan has a valid confirmation token.",
                "Previewing changes, registering strategies, or modifying paper orders.",
                "user_id, plan_id, confirmation_token, output_dir, db_path.",
                "commit_result, revalidation_result, audit_record.",
                "Writes strategy registry state only after confirmation and revalidation.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(),
            execution_handler=strategy_disable_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["strategy"],
            produced_outputs=["commit_result", "revalidation_result", "audit_record"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            legacy_names=["strategy_disable_commit"],
        ),
        ToolDefinition(
            name="capital.change.preview",
            display_name="Capital Change Preview",
            description=_description(
                "Create a confirmation proposal for a paper cash-flow change.",
                "A user submits deposit or withdrawal in the paper-trading account.",
                "Executing the cash-flow write, paper order execution, or historical replay.",
                "user_id, flow_type, amount, effective_date, reason, output_dir, db_path.",
                "operation_preview, confirmation_request, risk_impact.",
                "Creates an approval proposal only; no cash flow is saved.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "flow_type": {"type": "string"},
                    "amount": {"type": "number"},
                    "effective_date": {"type": "string"},
                    "reason": {"type": "string"},
                },
                required=["flow_type", "amount"],
            ),
            output_schema=_result_schema(),
            execution_handler=capital_change_preview_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["paper_account"],
            produced_outputs=["operation_preview", "confirmation_request", "risk_impact"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["capital_management_preview"],
        ),
        ToolDefinition(
            name="capital.change.commit",
            display_name="Capital Change Commit",
            description=_description(
                "Commit a confirmed paper cash-flow change after account-state revalidation.",
                "A pending capital_change plan has a valid confirmation token.",
                "Previewing cash flow, paper order execution, or historical replay.",
                "user_id, plan_id, confirmation_token, output_dir, db_path.",
                "commit_result, revalidation_result, audit_record.",
                "Writes one paper cash flow only after confirmation and revalidation.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(),
            execution_handler=capital_change_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["paper_account"],
            produced_outputs=["commit_result", "revalidation_result", "audit_record"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            legacy_names=["capital_management_execute"],
        ),
        ToolDefinition(
            name="backfill.preview",
            display_name="Backfill Preview",
            description=_description(
                "Create a confirmation proposal for paper-trading historical backfill.",
                "A user requests rebuilding or resuming paper-trading historical replay.",
                "Executing replay immediately, changing cash flow, or modifying strategy registry.",
                "user_id, start_date, end_date, initial_cash, force, resume, strategy options.",
                "operation_preview, confirmation_request, risk_impact.",
                "Creates an approval proposal only; no backfill is executed.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "initial_cash": {"type": "number"},
                    "force": {"type": "boolean"},
                    "resume": {"type": "boolean"},
                },
                required=["start_date"],
            ),
            output_schema=_result_schema(),
            execution_handler=backfill_preview_adapter,
            supported_actions=["preview_write_operation"],
            supported_objects=["paper_account"],
            produced_outputs=["operation_preview", "confirmation_request", "risk_impact"],
            operation_type=OP_PROPOSAL,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_PROPOSAL,
            legacy_names=["backfill_preview"],
        ),
        ToolDefinition(
            name="backfill.commit",
            display_name="Backfill Commit",
            description=_description(
                "Commit a confirmed paper-trading backfill plan after state revalidation.",
                "A pending paper_backfill plan has a valid confirmation token.",
                "Previewing replay, changing cash flow, or modifying strategy registry.",
                "user_id, plan_id, confirmation_token, output_dir, db_path.",
                "commit_result, revalidation_result, audit_record.",
                "Runs paper-trading backfill only after confirmation and revalidation.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(),
            execution_handler=backfill_commit_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["paper_account"],
            produced_outputs=["commit_result", "revalidation_result", "audit_record"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            legacy_names=["backfill_execute"],
        ),
        ToolDefinition(
            name="approval.confirm_plan",
            display_name="Approval Confirm Plan",
            description=_description(
                "Confirm an existing protected action plan through the unified write gateway.",
                "A user submits plan_id and confirmation_token for a supported pending plan.",
                "Creating previews, unsupported plan types, or direct unapproved writes.",
                "user_id, plan_id, confirmation_token, output_dir, db_path.",
                "commit_result, revalidation_result, audit_record.",
                "Dispatches to the correct protected writer only after approval is granted.",
            ),
            input_schema=_schema(
                {
                    "user_id": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "confirmation_token": {"type": "string"},
                },
                required=["plan_id", "confirmation_token"],
            ),
            output_schema=_result_schema(),
            execution_handler=approval_confirm_plan_adapter,
            supported_actions=["commit_write_operation"],
            supported_objects=["approval"],
            produced_outputs=["commit_result", "revalidation_result", "audit_record"],
            operation_type=OP_WRITE,
            allowed_agent_types=[AGENT_MAIN, AGENT_WRITE],
            permission_scope=OP_WRITE,
            requires_approval=True,
            legacy_names=["strategy_confirmation_execute"],
        ),
    ]


_GLOBAL_TOOL_REGISTRY_V2: ToolRegistry | None = None


def get_tool_registry_v2() -> ToolRegistry:
    global _GLOBAL_TOOL_REGISTRY_V2
    if _GLOBAL_TOOL_REGISTRY_V2 is None:
        _GLOBAL_TOOL_REGISTRY_V2 = ToolRegistry(build_core_tool_definitions())
    return _GLOBAL_TOOL_REGISTRY_V2


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
    context_bundle: Any | None = None,
    tool_context: dict[str, Any] | None = None,
    agent_type: str = AGENT_READ,
    approval_granted: bool = False,
    policy: RuntimePolicy | None = None,
    budget: RuntimeBudget | None = None,
    circuit_registry: CircuitBreakerRegistry | None = None,
) -> UnifiedToolResult:
    return ToolExecutor(
        policy=policy,
        budget=budget,
        circuit_registry=circuit_registry,
    ).execute(
        tool_name,
        arguments,
        context=context,
        context_bundle=context_bundle,
        tool_context=tool_context,
        agent_type=agent_type,
        approval_granted=approval_granted,
    )


def execute_tool_legacy_dict(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return execute_tool(*args, **kwargs).to_legacy_dict()
