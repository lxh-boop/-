from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from agent.agent_specs import (
    MARKET_INTELLIGENCE,
    PORTFOLIO_ANALYSIS,
    REPORTING,
    RISK_OPERATION,
    SUPERVISOR,
    get_agent_spec,
    list_agent_specs,
)
from agent.tool_engine import OP_READ, OP_SYSTEM, ToolDefinition, get_tool_registry_v2
from agent.tools.tool_registry import ToolCategory, ToolSpec, get_tool_registry
from agent.tools.tool_schemas import ToolPermission


INDEX_BUILDER_VERSION = "phase10.3-capability-index-v1"
REGISTRY_VERSION = "tool-registry-v2+legacy-preview-v1"
PERMISSION_VERSION = "agent-allowlist-v1"
MCP_CONFIG_VERSION = "mcp-allowlist-v1"

CORE_CAPABILITY_IDS = {
    "tool:portfolio_state",
    "tool:portfolio_risk",
    "tool:ranking",
    "tool:scheduler_status",
    "tool:report",
}

OUTPUTS_BY_TOOL: dict[str, set[str]] = {
    "portfolio_state": {"portfolio_state", "position_count", "account_summary"},
    "portfolio_risk": {"current_risk", "risk_factors", "limitations"},
    "portfolio.get_state": {"portfolio_state", "position_count", "account_summary", "positions", "orders"},
    "portfolio.get_account_summary": {"account_summary", "cash_state", "account"},
    "portfolio.get_positions": {"positions", "position_weights", "position_count"},
    "portfolio.get_orders": {"orders", "order_count", "latest_trade_date"},
    "portfolio.analyze_risk": {"current_risk", "risk_factors", "limitations", "risk_summary"},
    "portfolio.compare_risk_before_after": {"risk_before_after", "delta", "summary", "limitations"},
    "ranking": {"market_evidence", "evidence", "candidate_stocks", "reasons", "limitations"},
    "stock_lookup": {"stock_lookup", "market_evidence", "evidence", "reasons", "limitations"},
    "classic_stock_score": {"stock_lookup", "market_evidence", "evidence", "reasons", "limitations"},
    "classic_ranking": {"market_evidence", "evidence", "candidate_stocks", "signal_summary", "reasons", "limitations"},
    "market.compare_stocks": {"stock_comparison", "market_evidence", "evidence", "reasons", "limitations"},
    "stock_news": {"market_evidence", "evidence", "news_events", "reasons", "limitations"},
    "stock_rag": {"market_evidence", "evidence", "rag_contexts", "reasons", "limitations"},
    "news_search": {"market_evidence", "evidence", "news_events", "sources", "reasons", "limitations"},
    "rag_search": {"market_evidence", "evidence", "rag_contexts", "sources", "limitations"},
    "evidence.get_stock_evidence": {"market_evidence", "evidence", "sources", "reasons", "limitations"},
    "evidence.get_market_evidence": {"market_evidence", "evidence", "sources", "reasons", "limitations"},
    "mcp_market_risk_summary": {"market_evidence", "evidence", "mcp_sources", "sources", "limitations"},
    "stock_analysis": {"stock_analysis", "market_evidence", "evidence", "reasons", "limitations"},
    "position_recommendation": {"target_position", "reasons", "limitations"},
    "replacement_recommendation": {"replacement_candidates", "score_comparison", "risk_comparison", "reasons", "limitations"},
    "manual_position_operation_tool": {"operation_preview", "risk_impact", "confirmation_request"},
    "rebalance_plan": {"operation_preview", "target_portfolio", "confirmation_request"},
    "adjust_position": {"operation_preview", "risk_impact", "confirmation_request"},
    "paper_trade_preview": {"operation_preview", "order_preview", "cash_impact", "confirmation_request"},
    "paper_trade_execute": {"revalidation_result", "commit_result", "audit_record"},
    "paper_trading_execution_tool": {"revalidation_result", "commit_result", "audit_record"},
    "strategy_builder_tool": {"operation_preview", "strategy_manifest", "validation_result", "confirmation_request"},
    "strategy_management_tool": {"strategies", "operation_preview", "strategy_manifest", "confirmation_request"},
    "strategy.disable.preview": {"operation_preview", "confirmation_request", "risk_impact"},
    "strategy.disable.commit": {"commit_result", "revalidation_result", "audit_record"},
    "scheduler_status": {"scheduler_status"},
    "user_profile": {"user_profile", "constraints", "risk_assessment", "investment_goal"},
    "python_sandbox_analysis": {"sandbox_result", "calculation", "warnings"},
    "mcp_tool": {"market_evidence", "evidence", "mcp_sources", "limitations"},
    "report": {"report_summary"},
    "report_latest": {"report_summary"},
}

ACTION_BY_TOOL: dict[str, set[str]] = {
    "portfolio_state": {"query_portfolio_state"},
    "portfolio_risk": {"analyze_portfolio_risk", "recommend_portfolio", "recommend_portfolio_adjustment"},
    "portfolio.get_state": {"query_portfolio_state"},
    "portfolio.get_account_summary": {"query_portfolio_state"},
    "portfolio.get_positions": {"query_portfolio_state"},
    "portfolio.get_orders": {"query_portfolio_state"},
    "portfolio.analyze_risk": {"analyze_portfolio_risk", "recommend_portfolio", "recommend_portfolio_adjustment"},
    "portfolio.compare_risk_before_after": {"analyze_portfolio_risk", "recommend_portfolio", "recommend_portfolio_adjustment"},
    "ranking": {"recommend_portfolio", "recommend_portfolio_adjustment", "explain_previous_plan", "explain_portfolio_decision"},
    "stock_lookup": {"query_stock", "analyze_stock", "explain_previous_plan"},
    "classic_stock_score": {"query_stock", "analyze_stock", "explain_previous_plan"},
    "classic_ranking": {"recommend_portfolio", "recommend_portfolio_adjustment", "explain_previous_plan"},
    "market.compare_stocks": {"compare_stocks", "analyze_stock", "explain_previous_plan"},
    "stock_news": {"explain_previous_plan", "explain_portfolio_decision"},
    "stock_rag": {"explain_previous_plan", "explain_portfolio_decision"},
    "news_search": {"retrieve_evidence", "explain_previous_plan", "explain_portfolio_decision"},
    "rag_search": {"retrieve_evidence", "explain_previous_plan", "explain_portfolio_decision"},
    "evidence.get_stock_evidence": {"retrieve_evidence", "explain_previous_plan", "explain_portfolio_decision"},
    "evidence.get_market_evidence": {"retrieve_evidence", "explain_previous_plan", "explain_portfolio_decision"},
    "mcp_market_risk_summary": {"retrieve_evidence"},
    "stock_analysis": {"analyze_stock"},
    "position_recommendation": {"recommend_position"},
    "replacement_recommendation": {"recommend_replacement"},
    "manual_position_operation_tool": {"preview_write_operation"},
    "rebalance_plan": {"preview_write_operation"},
    "adjust_position": {"preview_write_operation"},
    "paper_trade_preview": {"preview_write_operation"},
    "paper_trade_execute": {"execute_confirmed_plan"},
    "paper_trading_execution_tool": {"execute_confirmed_plan"},
    "strategy_builder_tool": {"preview_write_operation"},
    "strategy_management_tool": {"preview_write_operation", "query_strategy"},
    "strategy.disable.preview": {"preview_write_operation"},
    "strategy.disable.commit": {"commit_write_operation"},
    "scheduler_status": {"query_scheduler_status"},
    "user_profile": {"query_user_profile"},
    "python_sandbox_analysis": {"run_readonly_python_analysis"},
    "mcp_tool": {"retrieve_evidence"},
    "report": {"query_report"},
    "report_latest": {"query_report"},
}


@dataclass(frozen=True)
class CapabilityRecord:
    capability_id: str
    name: str
    description: str
    supported_goal_actions: list[str] = field(default_factory=list)
    supported_objects: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    optional_inputs: list[str] = field(default_factory=list)
    produced_outputs: list[str] = field(default_factory=list)
    read_or_write: str = "read"
    tool_or_workflow: str = "tool"
    registered_tool_names: list[str] = field(default_factory=list)
    allowed_agent_types: list[str] = field(default_factory=list)
    permission_scope: str = "read"
    requires_approval: bool = False
    runtime_policy: dict[str, Any] = field(default_factory=dict)
    fallback_capabilities: list[str] = field(default_factory=list)
    implementation_files: list[str] = field(default_factory=list)
    version: str = "1"
    test_status: str = "unknown"
    enabled: bool = True
    sensitivity: str = "normal"
    content_hash: str = ""

    def to_dict(self, *, agent_view: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if agent_view:
            data.pop("implementation_files", None)
            data.pop("content_hash", None)
        return data


@dataclass(frozen=True)
class CapabilityIndex:
    index_version: str
    generated_at: str
    registry_version: str
    permission_version: str
    mcp_config_version: str
    content_hash: str
    builder_version: str
    records: list[CapabilityRecord] = field(default_factory=list)

    def to_dict(self, *, agent_view: bool = False) -> dict[str, Any]:
        return {
            "index_version": self.index_version,
            "generated_at": self.generated_at,
            "registry_version": self.registry_version,
            "permission_version": self.permission_version,
            "mcp_config_version": self.mcp_config_version,
            "content_hash": self.content_hash,
            "builder_version": self.builder_version,
            "records": [record.to_dict(agent_view=agent_view) for record in self.records],
        }


@dataclass(frozen=True)
class CapabilityGap:
    has_gap: bool
    missing_outputs: list[str] = field(default_factory=list)
    missing_capability_types: list[str] = field(default_factory=list)
    unavailable_capabilities: list[str] = field(default_factory=list)
    failed_capabilities: list[str] = field(default_factory=list)
    gap_reason: str = ""
    index_lookup_required: bool = False
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapabilitySelection:
    selected_capabilities: list[dict[str, Any]] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=list)
    required_inputs: list[str] = field(default_factory=list)
    artifact_dependencies: list[str] = field(default_factory=list)
    fallback_order: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapabilityIndexRepository:
    """Read-only runtime view over a trusted capability index."""

    def __init__(self, index: CapabilityIndex | None = None):
        self._index = index or build_trusted_capability_index()

    @property
    def index_version(self) -> str:
        return self._index.index_version

    def query(
        self,
        *,
        agent_identity: str,
        goal_action: str = "",
        missing_outputs: list[str] | None = None,
        permission_scope: str = "read",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        requested_outputs = {str(item) for item in (missing_outputs or []) if str(item).strip()}
        role = str(agent_identity or "")
        scope = str(permission_scope or "read")
        candidates: list[tuple[int, CapabilityRecord]] = []
        for record in self._index.records:
            if not record.enabled or record.test_status != "passed":
                continue
            if role not in set(record.allowed_agent_types):
                continue
            if scope == "read" and record.permission_scope != "read":
                continue
            if scope == "preview" and record.permission_scope != "preview":
                continue
            if scope == "write" and record.permission_scope != "write":
                continue
            if goal_action and goal_action not in set(record.supported_goal_actions):
                if requested_outputs and not requested_outputs & set(record.produced_outputs):
                    continue
                if not requested_outputs:
                    continue
            if requested_outputs and not requested_outputs & set(record.produced_outputs):
                continue
            score = len(requested_outputs & set(record.produced_outputs))
            if record.capability_id in CORE_CAPABILITY_IDS:
                score += 1
            if record.read_or_write == "read":
                score += 1
            candidates.append((score, record))
        candidates.sort(key=lambda item: (-item[0], item[1].capability_id))
        return [record.to_dict(agent_view=True) for _, record in candidates[: max(0, int(limit or 5))]]

    def report_stale_index(self, reason: str) -> dict[str, Any]:
        return {
            "event": "stale_capability_index_reported",
            "index_version": self.index_version,
            "reason": str(reason or "")[:300],
            "mutation_performed": False,
        }


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _input_names(schema: dict[str, Any] | None, *, required: bool) -> list[str]:
    schema = schema or {}
    if required:
        return [str(item) for item in (schema.get("required") or [])]
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required_set = set(schema.get("required") or [])
    return [str(name) for name in properties if name not in required_set]


def _permission_scope(spec: ToolSpec) -> str:
    if spec.permission == ToolPermission.READ:
        return "read"
    if spec.permission == ToolPermission.PREVIEW:
        return "preview"
    return "write"


def _allowed_agents_for_tool(tool_name: str, spec: ToolSpec) -> list[str]:
    allowed: set[str] = set()
    for item in list_agent_specs():
        if tool_name in set(item.get("tool_whitelist") or []):
            allowed.add(str(item.get("role") or ""))
    if spec.permission == ToolPermission.READ and tool_name in {"ranking", "portfolio_state", "portfolio_risk", "scheduler_status", "report"}:
        allowed.add(SUPERVISOR)
    if spec.permission == ToolPermission.PREVIEW:
        allowed.add(RISK_OPERATION)
    if spec.permission == ToolPermission.WRITE:
        allowed.add(RISK_OPERATION)
    if tool_name.startswith("mcp."):
        allowed.add(MARKET_INTELLIGENCE)
    return sorted(allowed)


def _record_from_tool(name: str, spec: ToolSpec) -> CapabilityRecord:
    produced = sorted(OUTPUTS_BY_TOOL.get(name) or {"tool_result"})
    actions = sorted(ACTION_BY_TOOL.get(name) or {"fallback_intent"})
    module_name = getattr(spec.handler, "__module__", "")
    content = {
        "name": name,
        "permission": spec.permission,
        "description": spec.description,
        "produced_outputs": produced,
        "actions": actions,
        "allowed_agents": _allowed_agents_for_tool(name, spec),
        "schema": spec.input_schema,
    }
    return CapabilityRecord(
        capability_id=f"tool:{name}",
        name=name,
        description=spec.description,
        supported_goal_actions=actions,
        supported_objects=["current_portfolio"] if "portfolio" in name or name in {"ranking", "position_recommendation"} else [],
        required_inputs=_input_names(spec.input_schema, required=True),
        optional_inputs=_input_names(spec.input_schema, required=False),
        produced_outputs=produced,
        read_or_write="read" if spec.permission == ToolPermission.READ else "write",
        tool_or_workflow="tool",
        registered_tool_names=[name],
        allowed_agent_types=_allowed_agents_for_tool(name, spec),
        permission_scope=_permission_scope(spec),
        requires_approval=bool(spec.requires_confirmation),
        runtime_policy={
            "timeout_seconds": spec.timeout_seconds,
            "retry_policy": dict(spec.retry_policy or {}),
            "concurrency_safe": bool(spec.concurrency_safe),
        },
        fallback_capabilities=[],
        implementation_files=[module_name] if module_name else [],
        version="1",
        test_status="passed",
        enabled=True,
        sensitivity="normal" if spec.permission == ToolPermission.READ else "restricted",
        content_hash=_hash_payload(content),
    )


def _allowed_agents_for_unified_tool(definition: ToolDefinition) -> list[str]:
    name = str(definition.name or "")
    allowed: set[str] = {SUPERVISOR}
    if name.startswith("market."):
        allowed.update({MARKET_INTELLIGENCE, PORTFOLIO_ANALYSIS, REPORTING})
    elif name.startswith("portfolio."):
        if definition.operation_type == OP_READ:
            allowed.update({PORTFOLIO_ANALYSIS, REPORTING})
        else:
            allowed.add(RISK_OPERATION)
    elif name.startswith("report."):
        allowed.add(REPORTING)
    elif name.startswith("system."):
        allowed.add(SUPERVISOR)
    elif name.startswith("user."):
        allowed.update({PORTFOLIO_ANALYSIS, RISK_OPERATION, REPORTING})
    elif name.startswith("sandbox."):
        allowed.add(SUPERVISOR)
    elif name.startswith("mcp."):
        allowed.update({MARKET_INTELLIGENCE, REPORTING})
    elif definition.operation_type not in {OP_READ, OP_SYSTEM}:
        allowed.add(RISK_OPERATION)
    return sorted(allowed)


def _record_from_unified_tool(definition: ToolDefinition) -> CapabilityRecord:
    public_view = definition.public_view()
    primary_name = str((definition.legacy_names or [definition.name])[0])
    required_inputs = _input_names(definition.input_schema, required=True)
    optional_inputs = _input_names(definition.input_schema, required=False)
    operation_type = str(definition.operation_type or OP_READ)
    if operation_type in {OP_READ, OP_SYSTEM}:
        permission_scope = "read"
    elif operation_type == "proposal":
        permission_scope = "preview"
    else:
        permission_scope = operation_type
    read_or_write = "read" if permission_scope == "read" else "write"
    content = {
        "name": definition.name,
        "legacy_names": definition.legacy_names,
        "description": definition.description,
        "schema": definition.input_schema,
        "operation_type": operation_type,
        "allowed_agents": _allowed_agents_for_unified_tool(definition),
    }
    return CapabilityRecord(
        capability_id=f"tool:{primary_name}",
        name=primary_name,
        description=str(public_view.get("description") or ""),
        supported_goal_actions=list(definition.supported_actions or []),
        supported_objects=list(definition.supported_objects or []),
        required_inputs=required_inputs,
        optional_inputs=optional_inputs,
        produced_outputs=sorted(set(definition.produced_outputs or OUTPUTS_BY_TOOL.get(primary_name) or {"tool_result"})),
        read_or_write=read_or_write,
        tool_or_workflow="tool",
        registered_tool_names=list(dict.fromkeys([primary_name, definition.name, *definition.legacy_names])),
        allowed_agent_types=_allowed_agents_for_unified_tool(definition),
        permission_scope=permission_scope,
        requires_approval=bool(definition.requires_approval),
        runtime_policy=dict(definition.runtime_policy or {}),
        fallback_capabilities=[],
        implementation_files=["agent.tool_engine"],
        version=str(definition.version or "1"),
        test_status="passed",
        enabled=bool(definition.enabled),
        sensitivity=str(definition.sensitivity or "normal"),
        content_hash=_hash_payload(content),
    )


def _workflow_records() -> list[CapabilityRecord]:
    content = {
        "workflow": "readonly_target_portfolio_allocation",
        "tools": ["portfolio_state", "portfolio_risk", "ranking"],
        "outputs": ["target_portfolio_allocation", "target_portfolio", "current_vs_target"],
    }
    return [
        CapabilityRecord(
            capability_id="workflow:readonly_target_portfolio_allocation",
            name="readonly_target_portfolio_allocation",
            description="Combine portfolio state, risk and ranking evidence into a read-only target portfolio allocation.",
            supported_goal_actions=[
                "generate_target_portfolio_allocation",
                "recommend_portfolio",
                "recommend_portfolio_adjustment",
            ],
            supported_objects=["current_portfolio", "market_evidence"],
            required_inputs=["portfolio_state", "portfolio_risk", "ranking"],
            optional_inputs=[],
            produced_outputs=["target_portfolio_allocation", "target_portfolio", "current_vs_target", "reasons", "limitations"],
            read_or_write="read",
            tool_or_workflow="workflow",
            registered_tool_names=["portfolio_state", "portfolio_risk", "ranking"],
            allowed_agent_types=[SUPERVISOR, PORTFOLIO_ANALYSIS, REPORTING],
            permission_scope="read",
            requires_approval=False,
            runtime_policy={"concurrency_safe": True, "uses_existing_task_outputs": True},
            fallback_capabilities=["tool:ranking", "tool:stock_news", "tool:stock_rag"],
            implementation_files=["agent.orchestration.result_aggregator"],
            version="1",
            test_status="passed",
            enabled=True,
            sensitivity="normal",
            content_hash=_hash_payload(content),
        )
    ]


def build_trusted_capability_index(
    *,
    include_mcp: bool = False,
    mcp_context: dict[str, Any] | None = None,
) -> CapabilityIndex:
    """Trusted builder: builds an index from registered tools and allowlists only."""

    records = [_record_from_unified_tool(definition) for definition in get_tool_registry_v2().list()]
    records.extend(_workflow_records())
    records = [record for record in records if record.enabled and record.allowed_agent_types]
    content_hash = _hash_payload([record.to_dict(agent_view=False) for record in records])
    generated_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    index_version = f"capidx-{content_hash[:12]}"
    return CapabilityIndex(
        index_version=index_version,
        generated_at=generated_at,
        registry_version=REGISTRY_VERSION,
        permission_version=PERMISSION_VERSION,
        mcp_config_version=MCP_CONFIG_VERSION,
        content_hash=content_hash,
        builder_version=INDEX_BUILDER_VERSION,
        records=records,
    )


def task_plan_produced_outputs(plan_payload: dict[str, Any] | Any) -> set[str]:
    tasks = plan_payload.get("tasks") if isinstance(plan_payload, dict) else getattr(plan_payload, "tasks", [])
    outputs: set[str] = set()
    for task in tasks or []:
        intent = str(task.get("intent") if isinstance(task, dict) else getattr(task, "intent", "") or "")
        outputs.update(OUTPUTS_BY_TOOL.get(intent) or set())
        if intent.startswith("mcp."):
            outputs.update({"market_evidence", "evidence", "reasons", "limitations"})
    intents = {
        str(task.get("intent") if isinstance(task, dict) else getattr(task, "intent", "") or "")
        for task in tasks or []
    }
    if {"portfolio_state", "portfolio_risk", "ranking"} <= intents:
        outputs.update({"target_portfolio", "current_vs_target", "reasons", "limitations"})
    return outputs


def detect_capability_gap(
    *,
    user_goal: dict[str, Any],
    task_plan: dict[str, Any],
    plan_validation: dict[str, Any],
    observe_result: dict[str, Any] | None = None,
    existing_artifacts: list[dict[str, Any]] | None = None,
) -> CapabilityGap:
    expected = [str(item) for item in (user_goal.get("expected_outputs") or []) if str(item).strip()]
    produced = task_plan_produced_outputs(task_plan)
    missing = [item for item in expected if item not in produced]
    if existing_artifacts:
        artifact_outputs = {
            output
            for artifact in existing_artifacts
            for output in (artifact.get("produced_outputs") or artifact.get("expected_outputs") or [])
        }
        missing = [item for item in missing if item not in artifact_outputs]

    validation_errors = [str(item) for item in (plan_validation.get("errors") or [])]
    observe_missing = []
    if isinstance(observe_result, dict) and observe_result.get("status") == "partial":
        observe_missing = [str(item) for item in (observe_result.get("missing_outputs") or [])]

    meaningful_errors = [
        item
        for item in validation_errors
        if "missing" in item and "pending_plan" not in item
    ]
    missing = list(dict.fromkeys([*missing, *observe_missing]))
    if not missing and not meaningful_errors:
        return CapabilityGap(
            has_gap=False,
            missing_outputs=[],
            gap_reason="current_plan_covers_expected_outputs",
            index_lookup_required=False,
            confidence=0.86,
        )
    return CapabilityGap(
        has_gap=True,
        missing_outputs=missing,
        missing_capability_types=meaningful_errors or ["output_coverage"],
        unavailable_capabilities=[],
        failed_capabilities=[],
        gap_reason="plan_or_observe_missing_required_outputs",
        index_lookup_required=True,
        confidence=0.78,
    )


def resolve_capability_gap(
    *,
    user_goal: dict[str, Any],
    capability_gap: CapabilityGap,
    agent_identity: str,
    runtime_budget: dict[str, Any] | None = None,
    existing_artifacts: list[dict[str, Any]] | None = None,
    index_repository: CapabilityIndexRepository | None = None,
    permission_scope: str = "read",
    limit: int = 5,
) -> tuple[CapabilitySelection, dict[str, Any]]:
    started = time.perf_counter()
    repo = index_repository or CapabilityIndexRepository()
    if not capability_gap.index_lookup_required:
        return CapabilitySelection(reason="index_lookup_not_required", confidence=0.9), {
            "index_lookup_triggered": False,
            "index_version": repo.index_version,
            "index_query_ms": 0.0,
            "candidate_count": 0,
        }

    candidates = repo.query(
        agent_identity=agent_identity,
        goal_action=str(user_goal.get("action") or ""),
        missing_outputs=capability_gap.missing_outputs,
        permission_scope=permission_scope,
        limit=limit,
    )
    selected = candidates[:1]
    outputs = sorted(
        {
            output
            for candidate in selected
            for output in (candidate.get("produced_outputs") or [])
        }
    )
    selection = CapabilitySelection(
        selected_capabilities=selected,
        expected_outputs=outputs,
        required_inputs=sorted(
            {
                item
                for candidate in selected
                for item in (candidate.get("required_inputs") or [])
            }
        ),
        artifact_dependencies=[
            str(item.get("artifact_id"))
            for item in (existing_artifacts or [])
            if isinstance(item, dict) and item.get("artifact_id")
        ],
        fallback_order=[
            str(item)
            for candidate in selected
            for item in (candidate.get("fallback_capabilities") or [])
        ],
        confidence=0.82 if selected else 0.0,
        reason="selected_best_authorized_capability" if selected else "no_authorized_capability_found",
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    trace = {
        "index_lookup_triggered": True,
        "index_version": repo.index_version,
        "index_query_ms": elapsed_ms,
        "candidate_count": len(candidates),
        "selected_capability_ids": [
            str(item.get("capability_id") or "")
            for item in selected
            if isinstance(item, dict)
        ],
    }
    return selection, trace


def capability_runtime_baseline() -> dict[str, Any]:
    repo = CapabilityIndexRepository()
    return {
        "capability_gap_detected": False,
        "index_lookup_triggered": False,
        "index_version": repo.index_version,
        "index_query_ms": 0.0,
        "candidate_count": 0,
        "selected_capability_ids": [],
        "artifact_lookup_count": 0,
        "artifact_reuse_count": 0,
        "artifact_ids_used": [],
        "fallback_used": False,
    }
