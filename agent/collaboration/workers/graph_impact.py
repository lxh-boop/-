"""Retrieve auditable financial-graph relations without business interpretation."""

from __future__ import annotations

from typing import Any

from agent.graph.contracts import GraphNodeKind, GraphRef, refs_from
from agent.graph.impact_service import GraphImpactService

from ..models import GraphAgentTask, GraphWorkerResult, MissingContextItem, ResultStatus
from .common import refs_from_dependencies, safe_public_value


def _unique_refs(refs: list[GraphRef]) -> list[GraphRef]:
    return refs_from([ref.to_dict() for ref in refs])


def _direct_refs(
    task: GraphAgentTask,
    *,
    arg_name: str,
    allowed_roles: set[str],
) -> list[GraphRef]:
    requested_ids = {
        str(item).strip()
        for item in task.args.get(arg_name) or []
        if str(item).strip()
    }
    candidates = task.focus_refs + task.context_refs
    if requested_ids:
        return [ref for ref in candidates if ref.node_id in requested_ids]
    return [ref for ref in candidates if str(ref.role or "") in allowed_roles]


def run_graph_impact(
    impact_service: GraphImpactService,
    task: GraphAgentTask,
    dependency_results: dict[str, dict[str, Any]],
    resolved_inputs: dict[str, Any] | None = None,
) -> GraphWorkerResult:
    if task.task_type != "retrieve_financial_relations":
        raise ValueError(f"unsupported_relation_task:{task.task_type}")

    source_task_ids = task.input_task_ids("source_graph_context")
    target_task_ids = task.input_task_ids("target_graph_context")

    source_refs = _direct_refs(
        task,
        arg_name="source_ref_ids",
        allowed_roles={"source", "cause", "event"},
    )
    target_refs = _direct_refs(
        task,
        arg_name="target_ref_ids",
        allowed_roles={"target", "impact_target", "portfolio", "holding"},
    )

    if source_task_ids:
        source_refs.extend(
            refs_from_dependencies(
                {
                    task_id: dependency_results[task_id]
                    for task_id in source_task_ids
                    if task_id in dependency_results
                },
                kinds={GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION, GraphNodeKind.OBJECT},
            )
        )
    if target_task_ids:
        target_refs.extend(
            refs_from_dependencies(
                {
                    task_id: dependency_results[task_id]
                    for task_id in target_task_ids
                    if task_id in dependency_results
                },
                kinds={GraphNodeKind.EVIDENCE, GraphNodeKind.ASSERTION, GraphNodeKind.OBJECT},
            )
        )

    source_refs = _unique_refs(source_refs)
    target_refs = _unique_refs(target_refs)
    missing: list[MissingContextItem] = []
    if not source_refs:
        missing.append(
            MissingContextItem(
                key="source_graph_context",
                description="缺少关系查找的来源图对象集合。",
                expected_format="source_ref_ids 或声明的上游图上下文",
                searched_sources=["task refs", "task.args.source_ref_ids", "declared upstream results"],
            )
        )
    if not target_refs:
        missing.append(
            MissingContextItem(
                key="target_graph_context",
                description="缺少关系查找的目标图对象集合。",
                expected_format="target_ref_ids 或声明的上游图上下文",
                searched_sources=["task refs", "task.args.target_ref_ids", "declared upstream results"],
            )
        )
    if missing:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            output_type="GraphRelationResult",
            data=None,
            error=None,
            focus_refs=task.focus_refs,
            summary="金融图关系查找缺少来源或目标图上下文。",
            missing_items=missing,
        )

    paths = impact_service.find_relation_paths(
        source_refs=source_refs,
        target_refs=target_refs,
        as_of_time=task.as_of_time,
    )
    summary = impact_service.summarize_relations(paths)
    payload = {
        "source_task_ids": source_task_ids,
        "target_task_ids": target_task_ids,
        "source_refs": [ref.to_dict() for ref in source_refs],
        "target_refs": [ref.to_dict() for ref in target_refs],
        "relation_paths": [path.to_dict() for path in paths],
        "relation_summary": safe_public_value(summary),
    }
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=ResultStatus.COMPLETED,
        output_type="GraphRelationResult",
        payload_schema="graph_relation_result.v1",
        payload=payload,
        data=payload,
        error=None,
        focus_refs=[*source_refs, *target_refs],
        summary=(
            f"已找到 {len(paths)} 条可追踪金融图关系路径。"
            if paths
            else "当前金融图中未找到符合条件的关系路径。"
        ),
        findings=[{"kind": "financial_relation_paths", **safe_public_value(summary)}],
        graph_path_refs=paths,
        evidence_refs=[ref for ref in source_refs if ref.node_kind == GraphNodeKind.EVIDENCE],
        confidence=max((path.confidence for path in paths), default=0.0),
        warnings=[] if paths else ["business_result_empty:no_financial_relation_path"],
        metadata={
            "relation_retrieval_only": True,
            "business_interpretation": False,
            "business_result_empty": not bool(paths),
        },
    )


__all__ = ["run_graph_impact"]
