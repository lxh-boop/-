from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.communication import MessageStore
from agent.memory.memory_context_bridge import build_memory_store_health_summary
from agent.react.react_context_bridge import build_react_health_summary
from application.handoff_service import build_handoff_health_summary
from application.reflection_service import build_reflection_health_summary
from evaluation.system_monitor import (
    build_system_monitor_snapshot,
    collect_and_store_system_monitor_snapshot,
    list_system_monitor_alerts,
    list_system_monitor_history,
)


class SystemMonitorApplicationService:
    @staticmethod
    def build_message_bus_health_summary(
        *,
        user_id: str = "default",
        output_dir: str | Path = "outputs",
    ) -> dict[str, Any]:
        try:
            root = Path(output_dir) / "message_logs" / str(user_id or "default")
            files = (
                sorted(root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
                if root.exists()
                else []
            )
            latest_run_id = files[0].stem if files else ""
            store = MessageStore(output_dir=output_dir)
            messages = (
                store.list_messages_by_run(latest_run_id, user_id=user_id)
                if latest_run_id
                else []
            )
            type_values = [
                str(getattr(message.message_type, "value", message.message_type))
                for message in messages
            ]
            return {
                "status": "ok",
                "latest_run_id": latest_run_id,
                "latest_run_message_count": len(messages),
                "message_store_summary": f"message_logs/{str(user_id or 'default')}/files={len(files)}",
                "error_message_count": sum(1 for item in type_values if item == "ERROR_RAISED"),
                "pending_approval_message_count": sum(1 for item in type_values if item == "APPROVAL_REQUESTED"),
                "artifact_message_count": sum(1 for item in type_values if item == "ARTIFACT_CREATED"),
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "latest_run_id": "",
                "latest_run_message_count": 0,
                "message_store_summary": "message_logs/unavailable",
                "error": type(exc).__name__,
                "error_message_count": 0,
                "pending_approval_message_count": 0,
                "artifact_message_count": 0,
            }


system_monitor_service = SystemMonitorApplicationService()


def build_message_bus_health_summary(**kwargs: Any) -> dict[str, Any]:
    return system_monitor_service.build_message_bus_health_summary(**kwargs)


__all__ = [
    "SystemMonitorApplicationService",
    "build_handoff_health_summary",
    "build_memory_store_health_summary",
    "build_message_bus_health_summary",
    "build_react_health_summary",
    "build_reflection_health_summary",
    "build_system_monitor_snapshot",
    "collect_and_store_system_monitor_snapshot",
    "list_system_monitor_alerts",
    "list_system_monitor_history",
]
