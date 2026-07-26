"""Authorized, observable execution for one registered tool call."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from agent.artifacts import save_tool_result_artifact
from agent.communication.integration import (
    approval_refs_from_payload,
    artifact_refs_from_result,
    context_ref_from_bundle,
    publish_agent_message,
    result_summary_payload,
)
from agent.communication.message_types import MessageType
from agent.console_trace import trace_event, trace_exception
from agent.context.context_builder import ContextManager
from agent.context.context_sanitizer import ContextSanitizer
from agent.react.integration import record_tool_observation
from agent.runtime_reliability import (
    CircuitBreakerRegistry,
    RuntimeBudget,
    RuntimePolicy,
    classify_runtime_error,
    execute_with_policy,
)

from .contracts import (
    AGENT_READ,
    OP_READ,
    OP_WRITE,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    UnifiedToolResult,
)
from .registry import ToolRegistry
from .validation import (
    normalise_raw_result,
    safe_argument_keys,
    validate_input,
    validate_output,
)


class ToolExecutor:
    """Execute registered tools behind common policy and audit boundaries."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        policy: RuntimePolicy | None = None,
        budget: RuntimeBudget | None = None,
        circuit_registry: CircuitBreakerRegistry | None = None,
    ) -> None:
        if registry is None:
            # Import lazily so ``agent.tool_engine`` can remain the compatibility
            # facade that owns the existing global business-tool catalogue.
            from agent.tool_engine import get_tool_registry_v2

            registry = get_tool_registry_v2()
        self.registry = registry
        self.policy = policy or RuntimePolicy.default()
        self.budget = budget or RuntimeBudget(self.policy)
        self.circuit_registry = circuit_registry or CircuitBreakerRegistry(
            self.policy
        )

    def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
        context_bundle: Any | None = None,
        tool_context: dict[str, Any] | None = None,
        agent_type: str = AGENT_READ,
        capability_id: str = "",
        approval_granted: bool = False,
    ) -> UnifiedToolResult:
        requested_name = str(tool_name or "")
        arguments = dict(arguments or {})
        trace_event(
            "tool.execute.start",
            {
                "tool_name": requested_name,
                "argument_keys": safe_argument_keys(arguments),
                "agent_type": agent_type,
                "capability_id": str(capability_id or ""),
                "approval_granted": approval_granted,
            },
            run_id=str((context or {}).get("run_id") or ""),
            task_id=str((context or {}).get("task_id") or ""),
        )
        definition = self.registry.get(requested_name)
        started_at = datetime.now().isoformat(timespec="seconds")
        started = time.perf_counter()
        if definition is None:
            return self._failure(
                requested_name,
                "unregistered_tool",
                "Tool is not registered.",
                started_at,
                started,
            )
        canonical_name = self.registry.canonical_name(requested_name)
        context = self._prepare_context(
            dict(context or {}),
            definition=definition,
            context_bundle=context_bundle,
            tool_context=tool_context,
        )

        def publish_tool_event(
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
                conversation_id=str(
                    context.get("conversation_id")
                    or context.get("session_id")
                    or ""
                ),
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
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "disabled_tool",
                },
                error={
                    "error_type": "disabled_tool",
                    "error_message": "Tool is disabled.",
                },
            )
            return self._failure(
                requested_name,
                "disabled_tool",
                "Tool is disabled.",
                started_at,
                started,
                canonical_name=canonical_name,
            )
        if agent_type not in set(definition.allowed_agent_types):
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "unauthorized_tool",
                },
                error={
                    "error_type": "unauthorized_tool",
                    "error_message": "Agent is not allowed to use this tool.",
                },
            )
            return self._failure(
                requested_name,
                "unauthorized_tool",
                "Agent is not allowed to use this tool.",
                started_at,
                started,
                canonical_name=canonical_name,
            )
        if (
            definition.visibility == TOOL_VISIBILITY_WORKER_PRIVATE
            and (
                not str(capability_id or "").strip()
                or str(capability_id or "").strip()
                not in set(definition.allowed_capability_ids)
            )
        ):
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "unauthorized_worker_capability",
                },
                error={
                    "error_type": "unauthorized_worker_capability",
                    "error_message": (
                        "Assigned capability is not allowed to use this private tool."
                    ),
                },
            )
            return self._failure(
                requested_name,
                "unauthorized_worker_capability",
                "Assigned capability is not allowed to use this private tool.",
                started_at,
                started,
                canonical_name=canonical_name,
            )
        if agent_type == AGENT_READ and definition.operation_type != OP_READ:
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "unauthorized_operation_type",
                },
                error={
                    "error_type": "unauthorized_operation_type",
                    "error_message": "Read worker cannot execute non-read tools.",
                },
            )
            return self._failure(
                requested_name,
                "unauthorized_operation_type",
                "Read worker cannot execute non-read tools.",
                started_at,
                started,
                canonical_name=canonical_name,
            )
        if definition.operation_type == OP_WRITE and not approval_granted:
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "approval_required",
                },
                error={
                    "error_type": "approval_required",
                    "error_message": "Write tool requires approval.",
                },
            )
            return self._failure(
                requested_name,
                "approval_required",
                "Write tool requires approval.",
                started_at,
                started,
                canonical_name=canonical_name,
            )
        input_errors = validate_input(definition, arguments)
        if input_errors:
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": "input_validation",
                    "argument_keys": safe_argument_keys(arguments),
                },
                error={
                    "error_type": "input_validation",
                    "error_message": ";".join(input_errors),
                },
            )
            return self._failure(
                requested_name,
                "input_validation",
                ";".join(input_errors),
                started_at,
                started,
                canonical_name=canonical_name,
            )

        publish_tool_event(
            MessageType.TOOL_CALL_REQUESTED,
            payload={
                "tool_name": requested_name,
                "canonical_tool_name": canonical_name,
                "argument_keys": safe_argument_keys(arguments),
                "agent_type": agent_type,
                "capability_id": str(capability_id or ""),
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
            result = normalise_raw_result(
                raw,
                requested_name=requested_name,
                canonical_name=canonical_name,
            )
            output_errors = validate_output(definition, result)
            if output_errors:
                result["success"] = False
                result["errors"] = (
                    list(result.get("errors") or []) + output_errors
                )
            artifact_id = ""
            artifact_ref: dict[str, Any] = {}
            if context.get("db_path") or context.get("output_dir"):
                try:
                    artifact_ref = save_tool_result_artifact(
                        db_path=context.get("db_path"),
                        output_dir=context.get("output_dir"),
                        user_id=str(context.get("user_id") or "default"),
                        run_id=str(context.get("run_id") or ""),
                        conversation_id=str(
                            context.get("session_id")
                            or context.get("conversation_id")
                            or ""
                        ),
                        task_id=str(context.get("task_id") or ""),
                        tool_name=requested_name,
                        result=result,
                    )
                    artifact_id = str(artifact_ref.get("artifact_id") or "")
                except Exception as exc:
                    result.setdefault("warnings", []).append(
                        f"artifact_save_failed:{type(exc).__name__}"
                    )
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
                duration_ms=round(
                    (time.perf_counter() - started) * 1000.0,
                    3,
                ),
                retry_count=int(runtime_metadata.retry_count),
                circuit_state=str(runtime_metadata.circuit_state),
            )
            refs = artifact_refs_from_result(unified)
            publish_tool_event(
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
                publish_tool_event(
                    MessageType.ARTIFACT_CREATED,
                    payload={
                        "tool_name": requested_name,
                        "artifact_count": len(refs),
                    },
                    artifact_refs=refs,
                )
            if unified.success and unified.data.get("plan_id"):
                publish_tool_event(
                    MessageType.APPROVAL_REQUESTED,
                    payload={
                        "plan_id": unified.data.get("plan_id"),
                        "plan_hash": unified.data.get("plan_hash"),
                        "status": (
                            unified.data.get("confirmation_status") or "pending"
                        ),
                        "token_present": bool(
                            unified.data.get("confirmation_token")
                        ),
                        "tool_name": requested_name,
                    },
                    approval_refs=approval_refs_from_payload(unified.data),
                )
            if not unified.success:
                publish_tool_event(
                    MessageType.ERROR_RAISED,
                    payload={
                        "tool_name": requested_name,
                        "error_type": unified.error_type,
                    },
                    error={
                        "error_type": unified.error_type,
                        "error_message": unified.error_message,
                    },
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
            publish_tool_event(
                MessageType.ERROR_RAISED,
                payload={
                    "tool_name": requested_name,
                    "error_type": classify_runtime_error(exc),
                },
                error={
                    "error_type": classify_runtime_error(exc),
                    "error_message": f"{type(exc).__name__}: {exc}"[:500],
                },
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
        prepared.setdefault(
            "context_mode",
            "minimal" if context_bundle is None else "bundle",
        )
        if context_bundle is not None:
            try:
                bundle_view = ContextSanitizer().sanitize_for_tool(
                    context_bundle,
                    permission_scope=definition.permission_scope,
                )
                prepared.setdefault("context_bundle", bundle_view)
                prepared.setdefault(
                    "context_bundle_id",
                    str(bundle_view.get("context_id") or ""),
                )
                prepared.setdefault(
                    "artifact_refs",
                    (bundle_view.get("artifact_context") or {}).get(
                        "artifact_refs"
                    )
                    or [],
                )
                prepared.setdefault(
                    "approval_context",
                    bundle_view.get("approval_context") or {},
                )
            except Exception:
                prepared.setdefault("context_bundle_error", "sanitize_failed")
        if tool_context:
            prepared.setdefault("tool_context", dict(tool_context or {}))
        return prepared

    @staticmethod
    def _update_context_bundle(
        context_bundle: Any | None,
        result: UnifiedToolResult,
    ) -> None:
        if context_bundle is None:
            return
        try:
            ContextManager().update_from_tool_result(
                context_bundle,
                result.to_dict(),
            )
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
            {
                "tool_name": tool_name,
                "canonical_tool_name": canonical_name or tool_name,
                "error_type": error_type,
                "message": message,
            },
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
            retry_count=int(
                (runtime_metadata or {}).get("retry_count") or 0
            ),
            circuit_state=str(
                (runtime_metadata or {}).get("circuit_state") or ""
            ),
        )
