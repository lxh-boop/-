"""Compose market-analysis results from Worker-private atomic observations."""

from __future__ import annotations

from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def compose_market_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="市场分析缺少明确的证券对象或必要上下文。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )

    observations = [
        {
            "tool_name": result.tool_name,
            "data": safe_public_value(result.data),
            "sources": safe_public_value(result.sources),
            "warnings": safe_public_value(result.warnings),
        }
        for result in execution.step_results.values()
    ]
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.COMPLETED
            if execution.success
            else ResultStatus.FAILED
        ),
        focus_refs=task.focus_refs,
        summary=(
            "已完成本地市场数据分析。"
            if execution.success
            else "本地市场数据分析失败。"
        ),
        findings=[
            {
                "kind": "market_analysis",
                "observations": observations,
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


__all__ = ["compose_market_result"]
