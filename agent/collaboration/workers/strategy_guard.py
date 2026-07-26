"""Compose proposal-only Strategy-Guard results from private tool observations."""

from __future__ import annotations

from agent.worker_planning.executor import WorkerPlanExecution

from ..models import GraphAgentTask, GraphWorkerResult, ResultStatus
from .common import safe_public_value


def compose_strategy_guard_result(
    task: GraphAgentTask,
    execution: WorkerPlanExecution,
) -> GraphWorkerResult:
    if execution.missing_items:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            focus_refs=task.focus_refs,
            summary="生成待审批方案前需要补充业务信息。",
            missing_items=execution.missing_items,
            warnings=execution.warnings,
        )
    selected = next(
        iter(execution.step_results.values()),
        None,
    )
    if selected is None:
        return GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.FAILED,
            focus_refs=task.focus_refs,
            summary="没有执行可用的 Proposal 工具。",
            warnings=[
                *execution.warnings,
                "proposal_tool_not_executed",
            ],
        )
    data = dict(selected.data or {})
    plan_id = str(data.get("plan_id") or "")
    proposal_id = str(data.get("proposal_id") or "")
    return GraphWorkerResult(
        task_id=task.task_id,
        agent_id=task.assigned_agent,
        status=(
            ResultStatus.PROPOSAL_READY
            if execution.success
            else ResultStatus.FAILED
        ),
        focus_refs=task.focus_refs,
        summary=(
            selected.message
            or (
                "已生成待审批方案。"
                if execution.success
                else "方案生成失败。"
            )
        ),
        findings=[
            {
                "kind": "proposal",
                "plan_id": plan_id,
                "proposal_id": proposal_id,
                "data": safe_public_value(data),
            }
        ],
        confidence=1.0 if execution.success else 0.0,
        warnings=list(
            dict.fromkeys(
                [
                    *execution.warnings,
                    *selected.warnings,
                    *selected.errors,
                ]
            )
        ),
        metadata={
            "plan_id": plan_id,
            "proposal_id": proposal_id,
            "requires_approval": execution.success,
            "tool_plan": {
                "ordered_step_ids": execution.ordered_step_ids,
                "tool_call_count": execution.tool_call_count,
            },
        },
    )


__all__ = ["compose_strategy_guard_result"]
