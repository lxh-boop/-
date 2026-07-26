"""Compose Portfolio-Worker results from atomic-tool observations."""

from __future__ import annotations

from agent.graph.contracts import GraphRef, refs_from
from agent.worker_planning.executor import WorkerPlanExecution

from ..models import (
    GraphAgentTask,
    GraphWorkerResult,
    MemoryUpdate,
    ResultStatus,
)
from .common import safe_public_value


def compose_portfolio_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="组合读取缺少必要的业务上下文。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )
    snapshot = next(
        (
            result.data
            for result in execution.step_results.values()
            if isinstance(result.data.get("portfolio_ref"), dict)
        ),
        {},
    )
    if not execution.success or not snapshot:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            focus_refs=task.focus_refs,
            summary="无法读取并生成当前组合快照。",
            warnings=list(
                dict.fromkeys(
                    [
                        *execution.warnings,
                        *[
                            error
                            for result in execution.step_results.values()
                            for error in result.errors
                        ],
                    ]
                )
            ),
        )
    portfolio_ref = GraphRef.from_dict(dict(snapshot["portfolio_ref"]))
    holding_refs = refs_from(snapshot.get("holding_refs") or [])
    unresolved = list(snapshot.get("unresolved_positions") or [])
    produced = [portfolio_ref, *holding_refs]
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.PARTIAL
            if unresolved
            else ResultStatus.COMPLETED
        ),
        focus_refs=[portfolio_ref],
        summary="已读取当前组合并生成可追踪图谱快照。",
        findings=[
            {
                "kind": "portfolio_snapshot",
                "portfolio_ref": portfolio_ref.to_dict(),
                "holding_refs": [
                    ref.to_dict() for ref in holding_refs
                ],
                "holding_count": len(holding_refs),
                "unresolved_position_count": len(unresolved),
                "portfolio_summary": safe_public_value(
                    snapshot.get("portfolio") or {}
                ),
            }
        ],
        confidence=1.0 if not unresolved else 0.75,
        warnings=(
            ["portfolio_contains_unresolved_positions"]
            if unresolved
            else []
        ),
        memory_updates=[
            MemoryUpdate(
                key="active_graph_refs",
                value=[ref.to_dict() for ref in produced],
                value_type="graph_ref_list",
                source_ref=task.task_id,
                confirmed=True,
                confidence=1.0,
                summary="当前组合快照及持仓对象引用。",
            )
        ],
        metadata={
            "produced_refs": [
                ref.to_dict() for ref in produced
            ],
            "unresolved_positions": safe_public_value(unresolved),
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
            },
        },
    )


__all__ = ["compose_portfolio_result"]
