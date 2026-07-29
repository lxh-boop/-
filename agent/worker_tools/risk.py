"""Atomic Worker-private portfolio-risk analysis tool."""

from __future__ import annotations

from typing import Any

from agent.collaboration.models import (
    ContextRequestCategory,
    MissingContextItem,
)
from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from
from agent.tool_runtime import (
    AGENT_WORKER,
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    description,
    result_schema,
    schema,
)
from agent.worker_planning.errors import WorkerContextRequired

from .backends import RiskToolBackend


RISK_ANALYZE_TOOL = "graph.risk.analyze_portfolio"


def _dependency_refs(plan_context: dict[str, Any]) -> list[GraphRef]:
    candidates: list[Any] = []
    for payload in dict(
        plan_context.get("dependency_results") or {}
    ).values():
        if not isinstance(payload, dict):
            continue
        candidates.extend(payload.get("focus_refs") or [])
        metadata = (
            payload.get("metadata")
            if isinstance(payload.get("metadata"), dict)
            else {}
        )
        candidates.extend(metadata.get("produced_refs") or [])
    candidates.extend(
        dict(plan_context.get("memory_values") or {}).get(
            "active_graph_refs",
            [],
        )
    )
    return refs_from(candidates)


def _risk_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    refs = _dependency_refs(plan_context)
    portfolio_ref = next(
        (
            ref
            for ref in refs
            if ref.node_kind == GraphNodeKind.OBJECT
            and "portfolio" in ref.node_id.lower()
        ),
        None,
    )
    if portfolio_ref is None:
        raise WorkerContextRequired(
            [
                MissingContextItem(
                    key="active_graph_refs",
                    description="需要选择要分析的当前组合",
                    expected_format="已确认的组合快照",
                    reason="风险分析缺少权威组合 GraphRef",
                    searched_sources=[
                        "dependency_results",
                        "session_memory",
                    ],
                    category=(
                        ContextRequestCategory.MEMORY_LOOKUP_REQUIRED
                    ),
                    value_schema={"type": "array", "items": {"type": "GraphRef"}},
                )
            ]
        )
    return {
        "user_id": task.user_id,
        "portfolio_ref": portfolio_ref.to_dict(),
    }


def build_risk_tool_definitions(
    provider: RiskToolBackend,
) -> list[ToolDefinition]:
    def analyze(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raw_ref = arguments.get("portfolio_ref")
        raw = provider.analyze_risk(
            user_id=str(
                arguments.get("user_id") or context.get("user_id") or ""
            ),
            output_dir=context.get("output_dir") or "outputs",
            db_path=context.get("db_path"),
            portfolio_ref=(
                GraphRef.from_dict(raw_ref)
                if isinstance(raw_ref, dict)
                else None
            ),
        )
        return {
            "success": bool(raw.get("success")),
            "message": str(raw.get("message") or ""),
            "data": {
                "portfolio_ref": raw.get("portfolio_ref"),
                "analysis": dict(raw.get("data") or {}),
                "records": list(raw.get("records") or []),
                "sources": list(raw.get("sources") or []),
            },
            "warnings": list(raw.get("warnings") or []),
            "errors": list(raw.get("errors") or []),
        }

    return [
        ToolDefinition(
            name=RISK_ANALYZE_TOOL,
            display_name="Analyze Portfolio Risk",
            description=description(
                "Analyze risk for one authoritative current-portfolio snapshot.",
                "The assigned capability has a portfolio GraphRef and needs risk metrics.",
                "Portfolio loading, target construction, proposals, or business writes.",
                "user_id and portfolio_ref.",
                "Normalized portfolio-risk analysis.",
            ),
            input_schema=schema(
                {
                    "user_id": {"type": "string"},
                    "portfolio_ref": {"type": "object"},
                },
                required=["user_id", "portfolio_ref"],
            ),
            output_schema=result_schema(["portfolio_ref", "analysis"]),
            execution_handler=analyze,
            argument_builder=_risk_arguments,
            supported_actions=["analyze_portfolio_risk"],
            supported_objects=["portfolio_graph_ref"],
            produced_outputs=["risk_analysis"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=["portfolio.risk_analysis"],
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "risk", "atomic"],
        )
    ]
