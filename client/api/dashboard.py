from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from client.api.base import call_operation, load_bootstrap
from client.api.types import LLMRuntimeSettings

_BOOTSTRAP = load_bootstrap("dashboard")
globals().update(_BOOTSTRAP)


@dataclass(slots=True)
class RemoteSchedulerHandle:
    scheduler_id: str = "default"
    running: bool = True


class RemoteRollingUpdateJob:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.job_id = str(payload.get("job_id") or "")
        self.log_path = payload.get("log_path")
        self.masked_command = list(payload.get("masked_command") or [])
        self._returncode: int | None = None

    def poll(self) -> int | None:
        payload = call_operation("dashboard", "rolling_update_job_status", job_id=self.job_id)
        self._returncode = payload.get("returncode")
        return payload.get("poll")

    def kill(self) -> None:
        payload = call_operation("dashboard", "rolling_update_job_kill", job_id=self.job_id)
        self._returncode = payload.get("returncode")

    @property
    def returncode(self) -> int | None:
        payload = call_operation("dashboard", "rolling_update_job_status", job_id=self.job_id)
        self._returncode = payload.get("returncode")
        return self._returncode

    def write_log(self, text: str) -> None:
        call_operation("dashboard", "rolling_update_job_write_log", job_id=self.job_id, text=str(text))

    def close(self) -> None:
        call_operation("dashboard", "rolling_update_job_close", job_id=self.job_id)


class DashboardRemoteService:
    def __getattr__(self, name: str):
        if name == "start_rolling_update_job":
            return self.start_rolling_update_job

        def remote_method(*args: Any, **kwargs: Any) -> Any:
            return call_operation("dashboard", str(name), *args, **kwargs)

        return remote_method

    @staticmethod
    def start_rolling_update_job(**kwargs: Any) -> RemoteRollingUpdateJob:
        payload = call_operation("dashboard", "start_rolling_update_job", **kwargs)
        return RemoteRollingUpdateJob(dict(payload or {}))


dashboard_service = DashboardRemoteService()


class LLMService:
    def __init__(self, settings: LLMRuntimeSettings | dict[str, Any] | Any) -> None:
        self.settings = LLMRuntimeSettings.from_value(settings)

    def validate_connection(self) -> tuple[bool, str]:
        result = call_operation("dashboard", "validate_llm_connection", settings=self.settings.to_dict())
        return tuple(result or (False, "Empty validation response"))  # type: ignore[return-value]


def resolve_active_llm_settings(*args: Any, **kwargs: Any) -> LLMRuntimeSettings:
    value = call_operation("dashboard", "resolve_active_llm_settings", *args, **kwargs)
    return LLMRuntimeSettings.from_value(value)


def create_scheduler() -> RemoteSchedulerHandle:
    payload = call_operation("dashboard", "create_scheduler")
    return RemoteSchedulerHandle(
        scheduler_id=str((payload or {}).get("scheduler_id") or "default"),
        running=bool((payload or {}).get("running", True)),
    )


def get_scheduler_jobs(scheduler: Any = None) -> Any:
    del scheduler
    return call_operation("dashboard", "get_scheduler_jobs")


def set_daily_retrain_job(*args: Any, **kwargs: Any) -> Any:
    kwargs.pop("scheduler", None)
    if args:
        args = args[1:]
    return call_operation("dashboard", "set_daily_retrain_job", *args, **kwargs)


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("dashboard", name, *args, **kwargs)

    wrapper.__name__ = name
    return wrapper


for _name in [
    "build_display_date_options",
    "classify_event_title",
    "build_mcp_context_from_local_config",
    "calculate_topk_rebalance",
    "build_stock_explanation_prompt",
    "create_project_model",
    "discover_mcp_tools",
    "downloaded_zoo_backends",
    "ensure_runtime_directories",
    "explain_prompt_with_llm",
    "get_ollama_version",
    "is_frozen_app",
    "is_prediction_only_date",
    "is_zoo_backend",
    "list_local_models",
    "list_model_names",
    "load_cached_ai_explanation",
    "load_daily_returns_for_strategy",
    "load_local_config",
    "load_selected_strategy",
    "mcp_sdk_version",
    "pull_model",
    "read_auto_retrain_log",
    "registered_zoo_backends",
    "reset_discovery_cache",
    "run_latest_t1_backtest",
    "save_local_config",
    "validate_local_model",
    "validate_tushare_token",
    "zoo_model_name_from_backend",
]:
    globals()[_name] = _remote(_name)


__all__ = [name for name in globals() if not name.startswith("_")]
