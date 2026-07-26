"""Compose Risk-Worker results from atomic-tool observations."""

from __future__ import annotations

from agent.graph.contracts import GraphRef
from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def compose_risk_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="风险分析缺少必要的组合上下文。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )
    payload = next(
        (
            result.data
            for result in execution.step_results.values()
            if "analysis" in result.data
        ),
        {},
    )
    raw_ref = payload.get("portfolio_ref")
    portfolio_ref = (
        GraphRef.from_dict(raw_ref)
        if isinstance(raw_ref, dict)
        else None
    )
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.COMPLETED
            if execution.success
            else ResultStatus.FAILED
        ),
        focus_refs=(
            [portfolio_ref] if portfolio_ref else task.focus_refs
        ),
        summary=(
            "已完成组合风险分析。"
            if execution.success
            else "组合风险分析失败。"
        ),
        findings=[
            {
                "kind": "portfolio_risk",
                "data": safe_public_value(
                    payload.get("analysis") or {}
                ),
                "record_count": len(payload.get("records") or []),
            }
        ],
        confidence=0.9 if execution.success else 0.0,
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
        metadata={
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
            }
        },
    )


__all__ = ["compose_risk_result"]
