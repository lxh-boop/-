"""Compose Diagnostic-Worker results from atomic-tool observations."""

from __future__ import annotations

from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus


def compose_diagnostic_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    payload = next(
        (
            result.data
            for result in execution.step_results.values()
            if "status" in result.data
        ),
        {},
    )
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
            "金融事实图连接正常。"
            if execution.success
            else "金融事实图连接检查失败。"
        ),
        findings=[
            {
                "kind": "graph_connectivity",
                "status": payload.get("status") or "failed",
                "graph_id": payload.get("graph_id") or "",
            }
        ],
        confidence=1.0 if execution.success else 0.0,
        warnings=execution.warnings,
        metadata={
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
            }
        },
    )


__all__ = ["compose_diagnostic_result"]
