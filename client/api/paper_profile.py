from __future__ import annotations
from typing import Any
from client.api.base import call_operation
from client.api.tasks import TaskHandle, submit_task


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("paper-profile", name, *args, **kwargs)
    wrapper.__name__ = name
    return wrapper


for _name in [
    "portfolio_output_dir",
    "user_output_dir",
    "format_classic_ranking_for_display",
    "load_classic_ranking_with_ai_adjustment",
    "build_ai_adjustment_detail",
    "load_current_ai_reliability_state",
    "load_scheduler_status_summary",
    "read_scheduler_log_tail",
    "has_required_paper_trading_profile",
    "save_classic_user_context",
    "load_classic_user_context",
    "cancel_pending_paper_cash_flow",
    "get_classic_user_profile_form_options",
]:
    globals()[_name] = _remote(_name)

__all__ = [name for name in globals() if not name.startswith("_")]


def submit_ai_news_adjustment(*args: Any, **kwargs: Any) -> TaskHandle:
    timeout_seconds = int(kwargs.pop("task_timeout_seconds", 1800))
    user_id = str(kwargs.get("user_id") or "")
    return submit_task("paper-profile.ai-news-adjustment", args=list(args), kwargs=kwargs, owner_id=user_id, session_id="ai-news-adjustment", timeout_seconds=timeout_seconds)

def submit_scheduler_manual_run(*args: Any, **kwargs: Any) -> TaskHandle:
    timeout_seconds = int(kwargs.pop("task_timeout_seconds", 1800))
    user_id = str(kwargs.get("user_id") or "scheduler")
    return submit_task("paper-profile.scheduler-manual", args=list(args), kwargs=kwargs, owner_id=user_id, session_id="scheduler-manual", timeout_seconds=timeout_seconds)
