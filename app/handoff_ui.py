from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.communication import MessageStore
from agent.handoff import HandoffSanitizer


HANDOFF_MESSAGE_TYPES = {
    "HANDOFF_REQUESTED",
    "HANDOFF_ACCEPTED",
    "HANDOFF_RESULT",
    "HANDOFF_BLOCKED",
}


def build_handoff_safe_summary(
    result: dict[str, Any] | None,
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    run_id: str = "",
) -> dict[str, Any]:
    data = result if isinstance(result, dict) else {}
    runtime = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    selected_run_id = str(run_id or data.get("run_id") or runtime.get("run_id") or "")
    orchestration = data.get("orchestration") if isinstance(data.get("orchestration"), dict) else {}
    summary = orchestration.get("phase17_handoff") if isinstance(orchestration.get("phase17_handoff"), dict) else {}
    if summary:
        safe = HandoffSanitizer().sanitize_for_ui(
            {
                "handoff_available": bool(summary.get("handoff_available")),
                "run_id": selected_run_id or summary.get("run_id") or "",
                "trace_id": summary.get("trace_id") or "",
                "handoff_count": int(summary.get("handoff_count") or 0),
                "roles_used": list(summary.get("roles_used") or []),
                "latest_handoff_status": str(summary.get("latest_handoff_status") or ""),
                "blocked_handoff_count": int(summary.get("blocked_handoff_count") or 0),
                "handoff_refs": list(summary.get("handoff_refs") or []),
                "handoff_role_summaries": list(summary.get("handoff_role_summaries") or []),
                "handoff_messages_seen": _handoff_message_count(selected_run_id, user_id=user_id, output_dir=output_dir),
                "safety": {
                    "secrets_redacted": True,
                    "raw_paths_hidden": True,
                    "raw_payload_hidden": True,
                },
            }
        )
        return safe if isinstance(safe, dict) else {}
    if not selected_run_id:
        return {
            "handoff_available": False,
            "run_id": "",
            "handoff_count": 0,
            "roles_used": [],
            "latest_handoff_status": "",
            "blocked_handoff_count": 0,
            "handoff_messages_seen": 0,
            "safety": {"secrets_redacted": True, "raw_paths_hidden": True, "raw_payload_hidden": True},
        }
    return _handoff_summary_from_messages(selected_run_id, user_id=user_id, output_dir=output_dir)


def format_handoff_caption(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict) or not summary.get("handoff_available"):
        return ""
    roles = ", ".join(str(item) for item in (summary.get("roles_used") or [])[:5]) or "-"
    return (
        "Handoff: "
        f"count={int(summary.get('handoff_count') or 0)} | "
        f"roles={roles} | "
        f"latest={summary.get('latest_handoff_status') or '-'} | "
        f"blocked={int(summary.get('blocked_handoff_count') or 0)}"
    )


def build_handoff_health_summary(*, user_id: str = "default", output_dir: str | Path = "outputs", limit: int = 10) -> dict[str, Any]:
    try:
        root = Path(output_dir) / "message_logs" / str(user_id or "default")
        files = sorted(root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True) if root.exists() else []
        latest_run_id = files[0].stem if files else ""
        summary = _handoff_summary_from_messages(latest_run_id, user_id=user_id, output_dir=output_dir) if latest_run_id else {}
        return {
            "status": "ok",
            "latest_run_id": latest_run_id,
            "run_file_count": len(files),
            "latest_handoff_count": int(summary.get("handoff_count") or 0),
            "latest_handoff_status": str(summary.get("latest_handoff_status") or ""),
            "blocked_handoff_count": int(summary.get("blocked_handoff_count") or 0),
            "roles_used": list(summary.get("roles_used") or [])[: int(limit or 10)],
            "handoff_messages_seen": int(summary.get("handoff_messages_seen") or 0),
            "safety": {"secrets_redacted": True, "raw_paths_hidden": True, "raw_payload_hidden": True},
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "latest_run_id": "",
            "run_file_count": 0,
            "latest_handoff_count": 0,
            "latest_handoff_status": "",
            "blocked_handoff_count": 0,
            "roles_used": [],
            "handoff_messages_seen": 0,
            "error": type(exc).__name__,
            "safety": {"secrets_redacted": True, "raw_paths_hidden": True, "raw_payload_hidden": True},
        }


def _handoff_summary_from_messages(run_id: str, *, user_id: str, output_dir: str | Path) -> dict[str, Any]:
    messages = MessageStore(output_dir=output_dir).list_messages_by_run(run_id, user_id=user_id) if run_id else []
    rows = []
    roles: list[str] = []
    blocked = 0
    for message in messages:
        message_type = str(getattr(getattr(message, "message_type", ""), "value", getattr(message, "message_type", "")))
        if message_type not in HANDOFF_MESSAGE_TYPES:
            continue
        payload = message.payload if isinstance(message.payload, dict) else {}
        target_role = str(payload.get("target_role") or getattr(message, "receiver", "") or "")
        if target_role:
            roles.append(target_role)
        if message_type == "HANDOFF_BLOCKED" or str(payload.get("status") or "").lower() == "blocked":
            blocked += 1
        rows.append(
            {
                "message_type": message_type,
                "handoff_id": str(payload.get("handoff_id") or ""),
                "target_role": target_role,
                "status": str(payload.get("status") or ""),
                "summary": str(payload.get("summary") or payload.get("reason") or "")[:240],
            }
        )
    safe_rows = HandoffSanitizer().sanitize_for_ui(rows)
    return {
        "handoff_available": bool(rows),
        "run_id": run_id,
        "handoff_count": sum(1 for row in rows if row["message_type"] in {"HANDOFF_RESULT", "HANDOFF_BLOCKED"}),
        "roles_used": sorted(set(role for role in roles if role and role != "COORDINATOR")),
        "latest_handoff_status": rows[-1]["status"] if rows else "",
        "blocked_handoff_count": blocked,
        "handoff_messages_seen": len(rows),
        "messages": safe_rows,
        "safety": {"secrets_redacted": True, "raw_paths_hidden": True, "raw_payload_hidden": True},
    }


def _handoff_message_count(run_id: str, *, user_id: str, output_dir: str | Path) -> int:
    if not run_id:
        return 0
    return int(_handoff_summary_from_messages(run_id, user_id=user_id, output_dir=output_dir).get("handoff_messages_seen") or 0)
