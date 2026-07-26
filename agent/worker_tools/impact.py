"""Atomic Worker-private tools for impact-path lookup and summarization."""

from __future__ import annotations

from typing import Any

from agent.collaboration.models import (
    ContextRequestCategory,
    MissingContextItem,
)
from agent.graph.contracts import (
    GraphNodeKind,
    GraphPathRef,
    GraphRef,
    refs_from,
)
from agent.tool_runtime import (
    AGENT_WORKER,
    OP_READ,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
    UnifiedToolResult,
    description,
    result_schema,
    schema,
)
from agent.worker_planning.errors import WorkerContextRequired

from .backends import ImpactToolBackend


IMPACT_FIND_PATHS_TOOL = "graph.impact.find_paths"
IMPACT_SUMMARIZE_PATHS_TOOL = "graph.impact.summarize_paths"


def _all_graph_refs(plan_context: dict[str, Any]) -> list[GraphRef]:
    task = plan_context["task"]
    candidates: list[Any] = [
        *[ref.to_dict() for ref in task.focus_refs],
        *[ref.to_dict() for ref in task.context_refs],
    ]
    for payload in dict(
        plan_context.get("dependency_results") or {}
    ).values():
        if not isinstance(payload, dict):
            continue
        candidates.extend(payload.get("focus_refs") or [])
        candidates.extend(payload.get("evidence_refs") or [])
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


def _find_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    refs = _all_graph_refs(plan_context)
    causes = [
        ref
        for ref in refs
        if ref.node_kind in {
            GraphNodeKind.EVIDENCE,
            GraphNodeKind.ASSERTION,
        }
        or (
            ref.node_kind == GraphNodeKind.OBJECT
            and ref.role in {"cause", "focus", "event"}
            and "portfolio" not in ref.node_id.lower()
        )
    ]
    portfolio_ref = next(
        (
            ref
            for ref in refs
            if ref.node_kind == GraphNodeKind.OBJECT
            and "portfolio" in ref.node_id.lower()
        ),
        None,
    )
    missing: list[MissingContextItem] = []
    if not causes:
        missing.append(
            MissingContextItem(
                key="cause_graph_refs",
                description="需要明确作为影响起点的事件或证据",
                expected_format="事件、证据或声明选择",
                reason="不能猜测影响路径的起点",
                searched_sources=[
                    "task_refs",
                    "dependency_results",
                    "session_memory",
                ],
                category=ContextRequestCategory.USER_INPUT_REQUIRED,
                value_schema={"type": "array", "items": {"type": "GraphRef"}},
            )
        )
    if portfolio_ref is None:
        missing.append(
            MissingContextItem(
                key="active_graph_refs",
                description="需要选择作为影响目标的当前组合",
                expected_format="已确认的组合快照",
                reason="影响路径分析缺少组合 GraphRef",
                searched_sources=[
                    "dependency_results",
                    "session_memory",
                ],
                category=ContextRequestCategory.MEMORY_LOOKUP_REQUIRED,
                value_schema={"type": "array", "items": {"type": "GraphRef"}},
            )
        )
    if missing:
        raise WorkerContextRequired(missing)
    return {
        "cause_refs": [ref.to_dict() for ref in causes],
        "portfolio_ref": portfolio_ref.to_dict(),
        "as_of_time": plan_context["task"].as_of_time,
    }


def _summary_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    path_rows: list[dict[str, Any]] = []
    for result in dict(plan_context.get("step_results") or {}).values():
        if not isinstance(result, UnifiedToolResult):
            continue
        path_rows.extend(
            dict(item)
            for item in result.data.get("paths") or []
            if isinstance(item, dict)
        )
    return {"paths": path_rows}


def build_impact_tool_definitions(
    impact_service: ImpactToolBackend,
) -> list[ToolDefinition]:
    def find_paths(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del context
        paths = impact_service.find_paths(
            cause_refs=refs_from(arguments.get("cause_refs") or []),
            portfolio_ref=GraphRef.from_dict(
                dict(arguments.get("portfolio_ref") or {})
            ),
            as_of_time=str(arguments.get("as_of_time") or ""),
        )
        return {
            "success": True,
            "paths": [path.to_dict() for path in paths],
        }

    def summarize_paths(
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        del context
        paths = [
            GraphPathRef(**dict(item))
            for item in arguments.get("paths") or []
            if isinstance(item, dict)
        ]
        return {
            "success": True,
            "summary": impact_service.summarize_paths(paths),
            "paths": [path.to_dict() for path in paths],
        }

    capability = ["graph.impact_analysis"]
    return [
        ToolDefinition(
            name=IMPACT_FIND_PATHS_TOOL,
            display_name="Find Portfolio Impact Paths",
            description=description(
                "Find validated graph paths from evidence or events to current holdings.",
                "The assigned capability has cause and portfolio GraphRefs.",
                "Evidence search, portfolio loading, path summarization, or writes.",
                "cause_refs, portfolio_ref, and as_of_time.",
                "Validated impact-path references.",
            ),
            input_schema=schema(
                {
                    "cause_refs": {"type": "array"},
                    "portfolio_ref": {"type": "object"},
                    "as_of_time": {"type": "string"},
                },
                required=["cause_refs", "portfolio_ref"],
            ),
            output_schema=result_schema(["paths"]),
            execution_handler=find_paths,
            argument_builder=_find_arguments,
            supported_actions=["find_impact_paths"],
            supported_objects=["evidence_graph_ref", "portfolio_graph_ref"],
            produced_outputs=["impact_paths"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=capability,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="read_only",
            audit_level="full",
            tags=["worker_private", "impact", "graph", "atomic"],
        ),
        ToolDefinition(
            name=IMPACT_SUMMARIZE_PATHS_TOOL,
            display_name="Summarize Portfolio Impact Paths",
            description=description(
                "Summarize a previously returned set of validated impact paths.",
                "A path-finding step completed and a holdings-level summary is needed.",
                "Graph queries, evidence search, portfolio loading, or writes.",
                "paths from the direct upstream tool result.",
                "Holding counts and grouped path summaries.",
            ),
            input_schema=schema(
                {"paths": {"type": "array"}},
                required=["paths"],
            ),
            output_schema=result_schema(["summary", "paths"]),
            execution_handler=summarize_paths,
            argument_builder=_summary_arguments,
            supported_actions=["summarize_impact_paths"],
            supported_objects=["graph_path_ref"],
            produced_outputs=["impact_summary"],
            required_dependency_outputs=["impact_paths"],
            operation_type=OP_READ,
            allowed_agent_types=[AGENT_WORKER],
            allowed_capability_ids=capability,
            permission_scope=OP_READ,
            visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
            idempotency="pure_transform",
            audit_level="full",
            tags=["worker_private", "impact", "atomic"],
        ),
    ]
