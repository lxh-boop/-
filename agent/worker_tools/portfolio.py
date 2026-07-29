"""Atomic Worker-private tools for portfolio state and graph snapshots."""

from __future__ import annotations

from typing import Any

from agent.tool_runtime import (
    AGENT_WORKER,
    OP_READ,
    OP_SYSTEM,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    UnifiedToolResult,
    description,
    result_schema,
    schema,
)

from .backends import PortfolioToolBackend


PORTFOLIO_READ_SNAPSHOT_TOOL = "graph.portfolio.read_snapshot"
PORTFOLIO_MATERIALIZE_SNAPSHOT_TOOL = (
    "graph.portfolio.materialize_snapshot"
)


def _read_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    return {"user_id": plan_context["task"].user_id}


def _snapshot_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    portfolio_payload: dict[str, Any] = {}
    for result in dict(plan_context.get("step_results") or {}).values():
        if not isinstance(result, UnifiedToolResult):
            continue
        candidate = result.data.get("portfolio_payload")
        if isinstance(candidate, dict):
            portfolio_payload = dict(candidate)
            break
    if not portfolio_payload:
        raise RuntimeError("portfolio_state_output_required")
    return {
        "portfolio_payload": portfolio_payload,
        "user_id": task.user_id,
        "as_of_time": task.as_of_time,
        "source_task_id": task.task_id,
        "source_agent_id": task.assigned_agent,
    }


def build_portfolio_tool_definitions(
    provider: PortfolioToolBackend,
) -> list[ToolDefinition]:
    def read_snapshot(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        raw = provider.read_portfolio_snapshot(
            user_id=str(
                arguments.get("user_id") or context.get("user_id") or ""
            ),
            output_dir=context.get("output_dir") or "outputs",
            db_path=context.get("db_path"),
        )
        return {
            "success": bool(raw.get("success")),
            "message": str(raw.get("message") or ""),
            "data": {"portfolio_payload": raw},
            "warnings": list(
                raw.get("warnings")
                or raw.get("consistency_warnings")
                or []
            ),
            "errors": list(
                raw.get("errors")
                or raw.get("consistency_errors")
                or []
            ),
        }

    def materialize_snapshot(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del context
        return provider.materialize_portfolio_snapshot(
            dict(arguments.get("portfolio_payload") or {}),
            user_id=str(arguments.get("user_id") or ""),
            as_of_time=str(arguments.get("as_of_time") or ""),
            source_task_id=str(arguments.get("source_task_id") or ""),
            source_agent_id=str(arguments.get("source_agent_id") or ""),
        )

    capabilities = [
        "portfolio.analysis",
    ]
    return [
        ToolDefinition(
            name=PORTFOLIO_READ_SNAPSHOT_TOOL,
            display_name="Read Portfolio Snapshot",
            description=description(
                "Read the current authoritative paper-portfolio state.",
                "The assigned capability needs account cash and positions.",
                "Graph materialization, risk analysis, proposals, or trading writes.",
                "user_id from the assigned task.",
                "A normalized portfolio-state payload.",
            ),
            input_schema=schema(
                {"user_id": {"type": "string"}},
                required=["user_id"],
            ),
            output_schema=result_schema(["portfolio_payload"]),
            execution_handler=read_snapshot,
            argument_builder=_read_arguments,
            supported_actions=["read_portfolio_snapshot"],
            supported_objects=["paper_portfolio"],
            produced_outputs=["portfolio_state"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=capabilities,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "portfolio", "atomic"],
        ),
        ToolDefinition(
            name=PORTFOLIO_MATERIALIZE_SNAPSHOT_TOOL,
            display_name="Materialize Portfolio Graph Snapshot",
            description=description(
                "Materialize a previously read portfolio state as a traceable graph snapshot.",
                "A portfolio-state step completed and downstream graph analysis needs GraphRefs.",
                "Reading account state, risk analysis, proposals, orders, or position writes.",
                "portfolio_payload and source task metadata.",
                "Portfolio and holding GraphRefs.",
                "Idempotently upserts a derived graph snapshot only.",
            ),
            input_schema=schema(
                {
                    "portfolio_payload": {"type": "object"},
                    "user_id": {"type": "string"},
                    "as_of_time": {"type": "string"},
                    "source_task_id": {"type": "string"},
                    "source_agent_id": {"type": "string"},
                },
                required=[
                    "portfolio_payload",
                    "user_id",
                    "source_task_id",
                    "source_agent_id",
                ],
            ),
            output_schema=result_schema(
                [
                    "portfolio_ref",
                    "holding_refs",
                    "unresolved_positions",
                    "portfolio",
                ]
            ),
            execution_handler=materialize_snapshot,
            argument_builder=_snapshot_arguments,
            supported_actions=["materialize_portfolio_snapshot"],
            supported_objects=["paper_portfolio_state"],
            produced_outputs=["portfolio_snapshot"],
            required_dependency_outputs=["portfolio_state"],
            operation_type=OP_SYSTEM,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=capabilities,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            side_effects=["derived_portfolio_graph_upsert"],
            mutates_business_state=False,
            idempotency="user_snapshot_upsert",
            audit_level="full",
            tags=["worker_private", "portfolio", "graph", "atomic"],
        ),
    ]
