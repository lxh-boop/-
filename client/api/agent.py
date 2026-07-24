from __future__ import annotations

from pathlib import Path
from typing import Any

from client.api.base import call_operation, load_bootstrap
from client.api.serialization import RemoteObject
from client.api.types import LLMRuntimeSettings

_BOOTSTRAP = load_bootstrap("agent")
globals().update(_BOOTSTRAP)


class AgentApplicationService:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or None

    def __getattr__(self, name: str):
        def remote_method(*args: Any, **kwargs: Any) -> Any:
            kwargs["_service_db_path"] = self.db_path
            if name == "run" and isinstance(kwargs.get("llm_settings"), LLMRuntimeSettings):
                kwargs["llm_settings"] = kwargs["llm_settings"].to_dict()
            return call_operation("agent", f"service.{name}", *args, **kwargs)

        return remote_method


class StrategyProposalService:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or None

    def __getattr__(self, name: str):
        def remote_method(*args: Any, **kwargs: Any) -> Any:
            kwargs["_service_db_path"] = self.db_path
            return call_operation("agent", f"strategy_proposal.{name}", *args, **kwargs)

        return remote_method


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("agent", name, *args, **kwargs)

    wrapper.__name__ = name
    return wrapper


for _name in [
    "build_handoff_safe_summary",
    "build_memory_safe_summary",
    "build_react_safe_summary",
    "build_reflection_safe_summary",
    "format_handoff_caption",
    "format_reflection_caption",
    "list_memory_records_safe_page",
    "list_safe_observation_summaries",
    "load_run_snapshot",
    "summarize_mcp_usage",
]:
    globals()[_name] = _remote(_name)


def trace_event(event: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return call_operation("agent", "trace_event", event, payload or {}, **kwargs)


def trace_exception(event: str, exc: BaseException, **kwargs: Any) -> Any:
    return call_operation(
        "agent",
        "trace_exception",
        event=str(event),
        message=f"{type(exc).__name__}: {exc}",
        **kwargs,
    )


__all__ = [name for name in globals() if not name.startswith("_")]
