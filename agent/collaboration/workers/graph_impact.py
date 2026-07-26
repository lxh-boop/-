"""Compose Impact-Worker results from atomic-tool observations."""

from __future__ import annotations

from agent.graph.contracts import GraphNodeKind, GraphPathRef, refs_from
from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def compose_graph_impact_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="影响路径分析缺少必要上下文。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )
    paths: list[GraphPathRef] = []
    summary: dict = {}
    for result in execution.step_results.values():
        paths.extend(
            GraphPathRef(**dict(item))
            for item in result.data.get("paths") or []
            if isinstance(item, dict)
        )
        if isinstance(result.data.get("summary"), dict):
            summary = dict(result.data["summary"])
    unique_paths = {
        path.path_id: path for path in paths
    }
    paths = list(unique_paths.values())
    if not summary:
        summary = {
            "holding_count": len(
                {path.end_ref.node_id for path in paths}
            ),
            "path_count": len(paths),
        }
    evidence_refs = refs_from(
        [
            path.start_ref.to_dict()
            for path in paths
            if path.start_ref.node_kind == GraphNodeKind.EVIDENCE
        ]
    )
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.COMPLETED
            if execution.success and paths
            else ResultStatus.PARTIAL
            if execution.success
            else ResultStatus.FAILED
        ),
        focus_refs=task.focus_refs,
        summary=(
            f"已找到 {len(paths)} 条可追踪影响路径，"
            f"涉及 {summary.get('holding_count', 0)} 个持仓。"
            if paths
            else "当前权威图中未找到可验证的影响路径。"
        ),
        findings=[
            {
                "kind": "portfolio_impact_paths",
                **safe_public_value(summary),
            }
        ],
        graph_path_refs=paths,
        evidence_refs=evidence_refs,
        confidence=max(
            (path.confidence for path in paths),
            default=0.0,
        ),
        warnings=(
            execution.warnings
            if paths
            else [
                *execution.warnings,
                "no_validated_impact_path",
            ]
        ),
        metadata={
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
            }
        },
    )


__all__ = ["compose_graph_impact_result"]
