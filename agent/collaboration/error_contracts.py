"""Minimal Worker-to-MainAgent error contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class WorkerEscalation:
    """Safe capability-level error after Worker-local handling is exhausted."""

    error_id: str
    operation: str
    reason: str

    @classmethod
    def create(cls, *, error_id: str, operation: str, reason: str) -> "WorkerEscalation":
        return cls(
            error_id=str(error_id or "worker_capability_failed")[:120],
            operation=str(operation or "worker_operation")[:500],
            reason=str(reason or "Worker could not complete the capability.")[:2000],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def escalation_from_worker_result(task: Any, result: Any) -> WorkerEscalation | None:
    status = str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", "")))
    if status in {"completed", "proposal_ready"}:
        return None
    raw_error = dict(getattr(result, "error", None) or {})
    missing_items = list(getattr(result, "missing_items", None) or [])
    source_error = dict(raw_error.get("source_tool_error") or {})
    declared_missing_parameter = any(
        "parameter" in str(getattr(item, "reason", "") or "").lower()
        for item in missing_items
    )
    default_need_context_error = (
        "user_input_required" if declared_missing_parameter else "worker_context_unresolved"
    )
    error_id = str(
        raw_error.get("error_id") or raw_error.get("code")
        or source_error.get("error_id")
        or (default_need_context_error if status == "need_context" else "worker_capability_failed")
    )
    reason = str(raw_error.get("reason") or raw_error.get("message") or source_error.get("reason") or "")
    if not reason and missing_items:
        reason = "；".join(
            str(getattr(item, "description", "") or "")
            for item in missing_items if getattr(item, "description", "")
        )
    if not reason:
        reason = str(getattr(result, "summary", "") or "Worker could not complete the capability.")
    return WorkerEscalation.create(
        error_id=error_id,
        operation=str(getattr(task, "objective", "") or getattr(task, "boundary_id", "") or ""),
        reason=reason,
    )


__all__ = ["WorkerEscalation", "escalation_from_worker_result"]
