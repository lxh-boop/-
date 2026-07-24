from __future__ import annotations
from typing import Any
from client.api.base import call_operation


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("system-monitor", name, *args, **kwargs)
    wrapper.__name__ = name
    return wrapper

for _name in [
    "build_handoff_health_summary",
    "build_memory_store_health_summary",
    "build_message_bus_health_summary",
    "build_react_health_summary",
    "build_reflection_health_summary",
    "build_system_monitor_snapshot",
    "collect_and_store_system_monitor_snapshot",
    "list_system_monitor_alerts",
    "list_system_monitor_history",
]:
    globals()[_name] = _remote(_name)

__all__ = [name for name in globals() if not name.startswith("_")]
