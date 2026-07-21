from __future__ import annotations

from typing import Any

from agent.context.context_types import ContextBundle


def build_reporter_context(
    bundle: ContextBundle,
    *,
    user_goal: dict[str, Any],
    result_summary: dict[str, Any],
    completion: dict[str, Any],
) -> dict[str, Any]:
    return {
        "context_id": bundle.context_id,
        "run_id": bundle.run_id,
        "user_goal": dict(user_goal or {}),
        "result_summary": dict(result_summary or {}),
        "completion": dict(completion or {}),
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
        "evidence_source_refs": list(bundle.evidence_context.source_refs),
    }


__all__ = ["build_reporter_context"]
