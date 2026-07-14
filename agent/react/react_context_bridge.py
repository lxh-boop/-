from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.communication import MessageStore

from .observe_sanitizer import ObserveSanitizer
from .observe_store import ObserveStore
from .observation_types import ObservationEvent, ObservationSeverity


REPLAN_MESSAGE_TYPES = {
    "REPLAN_REQUESTED",
    "REPLAN_SKIPPED",
    "REPLAN_APPLIED",
    "REPLAN_BLOCKED",
}


def build_react_safe_summary(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    run_id: str = "",
) -> dict[str, Any]:
    """Return lightweight ReAct/Observe counters for UI display."""
    latest_run_id = str(run_id or "").strip() or _latest_react_run_id(user_id=user_id, output_dir=output_dir)
    observations = _load_observations(user_id=user_id, output_dir=output_dir, run_id=latest_run_id)
    type_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for event in observations:
        type_key = str(event.observation_type.value)
        severity_key = str(event.severity.value)
        type_counts[type_key] = type_counts.get(type_key, 0) + 1
        severity_counts[severity_key] = severity_counts.get(severity_key, 0) + 1

    messages = []
    if latest_run_id:
        try:
            messages = MessageStore(output_dir=output_dir).list_messages_by_run(latest_run_id, user_id=user_id)
        except Exception:
            messages = []
    message_types = [
        str(getattr(getattr(message, "message_type", ""), "value", getattr(message, "message_type", "")))
        for message in messages
    ]
    replan_counts = {
        message_type: message_types.count(message_type)
        for message_type in sorted(REPLAN_MESSAGE_TYPES)
        if message_types.count(message_type)
    }

    latest = observations[-1] if observations else None
    return {
        "status": "ok",
        "run_id": latest_run_id,
        "observation_count": len(observations),
        "blocking_observation_count": sum(1 for item in observations if item.severity == ObservationSeverity.BLOCKING),
        "latest_observation_type": str(latest.observation_type.value) if latest else "",
        "latest_observation_id": str(latest.observation_id) if latest else "",
        "observation_type_counts": dict(sorted(type_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "replan_message_count": sum(replan_counts.values()),
        "replan_message_counts": replan_counts,
        "safety": {
            "secrets_redacted": True,
            "raw_paths_hidden": True,
            "raw_payload_hidden": True,
        },
    }


def build_react_health_summary(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    """Return safe health counters for the system monitor."""
    try:
        root = Path(output_dir) / "react_logs" / _safe_path_part(user_id or "default")
        files = sorted(root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True) if root.exists() else []
        latest_run_id = files[0].stem if files else ""
        summary = build_react_safe_summary(user_id=user_id, output_dir=output_dir, run_id=latest_run_id)
        summary.update(
            {
                "react_log_summary": f"react_logs/{_safe_path_part(user_id or 'default')}/files={len(files)}",
                "latest_run_id": latest_run_id,
                "run_file_count": len(files),
            }
        )
        return summary
    except Exception as exc:
        return {
            "status": "unavailable",
            "latest_run_id": "",
            "run_file_count": 0,
            "react_log_summary": "react_logs/unavailable",
            "observation_count": 0,
            "blocking_observation_count": 0,
            "replan_message_count": 0,
            "error": type(exc).__name__,
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
            },
        }


def list_safe_observation_summaries(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    run_id: str = "",
    limit: int = 5,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return paginated UI-safe observation rows without raw payloads."""
    observations = _load_observations(user_id=user_id, output_dir=output_dir, run_id=str(run_id or "").strip())
    start = max(0, int(offset or 0))
    end = start + max(1, min(50, int(limit or 5)))
    sanitizer = ObserveSanitizer()
    rows: list[dict[str, Any]] = []
    for event in list(reversed(observations))[start:end]:
        safe = sanitizer.sanitize_for_ui(event)
        rows.append(
            {
                "created_at": str(safe.get("created_at") or "")[:19],
                "observation_id": str(safe.get("observation_id") or "")[:96],
                "observation_type": str(safe.get("observation_type") or "")[:64],
                "severity": str(safe.get("severity") or "")[:32],
                "status": str(safe.get("status") or "")[:32],
                "summary": str(safe.get("summary") or "")[:220],
                "context_ref_count": len(safe.get("context_refs") or []),
                "artifact_ref_count": len(safe.get("artifact_refs") or []),
                "memory_ref_count": len(safe.get("memory_refs") or []),
                "tool_call_ref_count": len(safe.get("tool_call_refs") or []),
            }
        )
    return rows


def _load_observations(*, user_id: str, output_dir: str | Path, run_id: str) -> list[ObservationEvent]:
    if not run_id:
        return []
    try:
        return ObserveStore(output_dir=output_dir).list_observations_by_run(run_id, user_id=user_id)
    except Exception:
        return []


def _latest_react_run_id(*, user_id: str, output_dir: str | Path) -> str:
    root = Path(output_dir) / "react_logs" / _safe_path_part(user_id or "default")
    if not root.exists():
        return ""
    files = sorted(root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0].stem if files else ""


def _safe_path_part(value: str) -> str:
    text = str(value or "default")
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in text)[:120] or "default"
