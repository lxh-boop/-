from __future__ import annotations

from typing import Any

from client.api.base import call_operation, load_bootstrap
from client.api.types import PipelineStatus
from client.api.tasks import TaskHandle, submit_task

_BOOTSTRAP = load_bootstrap("paper-trading")
for _key, _value in _BOOTSTRAP.items():
    if _key != "PipelineStatus":
        globals()[_key] = _value


def _remote(name: str):
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return call_operation("paper-trading", name, *args, **kwargs)

    wrapper.__name__ = name
    return wrapper


for _name in [
    "cancel_pending_paper_cash_flow",
    "path_cache_version",
    "paper_cache_versions",
    "load_latest_ranking",
    "daily_position_cache_versions",
    "daily_order_cache_versions",
    "cash_flow_cache_versions",
    "ai_reliability_cache_version",
    "execute_confirmed_plan_v2",
    "execute_tool",
    "explain_stock_decision_attribution",
    "format_permission_summary",
    "get_classic_user_profile_form_options",
    "has_required_paper_trading_profile",
    "list_daily_order_snapshot_dates",
    "list_daily_position_snapshot_dates",
    "list_replay_audit_dates",
    "list_replay_audit_runs",
    "load_ai_reliability_state",
    "load_classic_user_context",
    "load_daily_order_snapshot",
    "load_daily_position_snapshot",
    "load_paper_backfill_status",
    "load_paper_cash_flows",
    "load_paper_trading_snapshot",
    "load_replay_audit_day",
    "load_replay_audit_markdown",
    "normalize_trading_permissions",
    "ranking_exists",
    "read_csv",
    "render_decision_attribution_markdown",
    "save_classic_user_context",
    "sync_event_cache_to_agent_db",
]:
    globals()[_name] = _remote(_name)


__all__ = [name for name in globals() if not name.startswith("_")]


def submit_paper_trading_update(*args: Any, sync_kwargs: dict[str, Any] | None = None, **kwargs: Any) -> TaskHandle:
    timeout_seconds = int(kwargs.pop("task_timeout_seconds", 1800))
    user_id = str(kwargs.get("user_id") or "")
    return submit_task(
        "paper-trading.update",
        args=list(args),
        kwargs={**kwargs, "sync_kwargs": dict(sync_kwargs or {})},
        owner_id=user_id,
        session_id="paper-trading-update",
        metadata={"surface": "ai-paper-trading"},
        timeout_seconds=timeout_seconds,
    )
