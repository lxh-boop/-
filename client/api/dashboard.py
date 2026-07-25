from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from client.api.base import call_operation, load_bootstrap
from client.api.types import LLMRuntimeSettings
from client.api.tasks import TaskHandle, find_latest_task, submit_task

_BOOTSTRAP = load_bootstrap("dashboard")
globals().update(_BOOTSTRAP)


@dataclass(slots=True)
class RemoteSchedulerHandle:
    scheduler_id: str = "default"
    running: bool = True


class RemoteRollingUpdateJob:
    def __init__(self, handle: TaskHandle | dict[str, Any]) -> None:
        self.handle = handle if isinstance(handle, TaskHandle) else TaskHandle(str(handle.get("task_id") or ""))
        self.job_id = self.handle.task_id
        self.log_path = None
        self.masked_command: list[str] = []
        self._returncode: int | None = None

    def poll(self) -> int | None:
        task = self.handle.status()
        status = str(task.get("status") or "")
        if status in {"queued", "running", "cancelling"}:
            return None
        self._returncode = 0 if status == "succeeded" else 1
        result = task.get("result") or {}
        if isinstance(result, dict):
            self.log_path = result.get("log_path")
            self.masked_command = list(result.get("masked_command") or [])
        return self._returncode

    def kill(self) -> None:
        self.handle.cancel()
        self._returncode = 1

    @property
    def returncode(self) -> int | None:
        self.poll()
        return self._returncode

    def write_log(self, text: str) -> None:
        del text

    def close(self) -> None:
        return None

    def status(self) -> dict[str, Any]:
        return self.handle.status()


class DashboardRemoteService:
    def __getattr__(self, name: str):
        if name == "start_rolling_update_job":
            return self.start_rolling_update_job

        def remote_method(*args: Any, **kwargs: Any) -> Any:
            return call_operation("dashboard", str(name), *args, **kwargs)

        return remote_method

    @staticmethod
    def start_rolling_update_job(**kwargs: Any) -> RemoteRollingUpdateJob:
        estimated_seconds = int(kwargs.pop("estimated_seconds", 300))
        timeout_seconds = int(kwargs.pop("timeout_seconds", 3600))
        handle = submit_task(
            "dashboard.rolling_update",
            kwargs={**kwargs, "estimated_seconds": estimated_seconds},
            owner_id="dashboard",
            session_id="rolling-update",
            metadata={"surface": "dashboard"},
            timeout_seconds=timeout_seconds,
        )
        return RemoteRollingUpdateJob(handle)

    @staticmethod
    def find_active_rolling_update() -> RemoteRollingUpdateJob | None:
        task = find_latest_task(owner_id="dashboard", session_id="rolling-update", task_type="dashboard.rolling_update", active_only=True)
        return RemoteRollingUpdateJob(task) if task else None


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
    "save_local_config",
    "validate_local_model",
    "validate_tushare_token",
    "zoo_model_name_from_backend",
]:
    globals()[_name] = _remote(_name)


__all__ = [name for name in globals() if not name.startswith("_")]


def submit_latest_t1_backtest(*args: Any, **kwargs: Any) -> TaskHandle:
    timeout_seconds = int(kwargs.pop("task_timeout_seconds", 3600))
    return submit_task(
        "dashboard.backtest",
        args=list(args),
        kwargs=kwargs,
        owner_id="dashboard",
        session_id="backtest",
        metadata={"surface": "backtest"},
        timeout_seconds=timeout_seconds,
    )


def find_active_backtest() -> TaskHandle | None:
    task = find_latest_task(owner_id="dashboard", session_id="backtest", task_type="dashboard.backtest", active_only=True)
    return TaskHandle(str(task.get("task_id") or "")) if task else None
