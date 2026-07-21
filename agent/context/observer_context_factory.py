from __future__ import annotations

from typing import Any

from agent.context.context_types import ContextBundle


def build_observer_context(
    bundle: ContextBundle,
    *,
    user_goal: dict[str, Any],
    task_plan: dict[str, Any] | None,
    result: dict[str, Any],
    orchestration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return {
        "context_id": bundle.context_id,
        "run_id": bundle.run_id,
        "user_goal": dict(user_goal or {}),
        "task_plan": dict(task_plan or {}),
        "result_summary": {
            "success": bool(result.get("success")),
            "tool_name": str(result.get("tool_name") or ""),
            "message": str(result.get("message") or "")[:1200],
            "produced_output_keys": sorted(data.keys()),
            "warnings": list(result.get("warnings") or [])[:20],
            "errors": list(result.get("errors") or [])[:20],
        },
        "orchestration": {
            "execution_status": str((orchestration or {}).get("execution_status") or ""),
            "replan_count": int((orchestration or {}).get("replan_count") or 0),
        },
        "memory_refs": list(bundle.memory_context.memory_refs),
        "artifact_refs": list(bundle.artifact_context.artifact_refs),
    }


__all__ = ["build_observer_context"]
