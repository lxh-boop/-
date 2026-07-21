from __future__ import annotations

from typing import Any

from agent.context.context_types import ContextBundle


def build_tool_execution_context(
    bundle: ContextBundle,
    *,
    user_goal: dict[str, Any] | None = None,
    task_plan: dict[str, Any] | None = None,
    runtime_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "context_id": bundle.context_id,
        "user_id": bundle.user_id,
        "conversation_id": bundle.conversation_id,
        "run_id": bundle.run_id,
        "user_goal": dict(user_goal or {}),
        "task_plan": dict(task_plan or {}),
"working_state": {
    "phase": bundle.runtime_context.phase,
    "completed_tasks": list(bundle.runtime_context.completed_tasks),
    "failed_tasks": list(bundle.runtime_context.failed_tasks),
    "pending_tasks": list(bundle.runtime_context.pending_tasks),
    "replan_count": bundle.runtime_context.replan_count,
    "missing_outputs": list(bundle.runtime_context.missing_outputs),
    "completion_status": bundle.runtime_context.completion_status,
},
        "memory_refs": list(bundle.memory_context.memory_refs),
        "artifact_refs": list(bundle.artifact_context.artifact_refs),
        "approval": {
            "pending_plan_id": bundle.approval_context.pending_plan_id,
            "status": bundle.approval_context.status,
            "token_present": bundle.approval_context.token_present,
        },
        **dict(runtime_fields or {}),
    }


__all__ = ["build_tool_execution_context"]
