from __future__ import annotations

import csv
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from local_config import load_local_config
from scheduler.job_state import load_latest_job_status
from scheduler.trading_calendar import get_latest_trading_day


SCHEDULER_JOB_ID = "stock_daily_configured_update"
CATCH_UP_JOB_ID = "stock_daily_startup_catch_up"
RUNTIME_STATUS_PATH = Path("runtime") / "jobs" / "scheduler_runtime_status.json"
SCHEDULER_TIMEZONE = "Asia/Shanghai"
_SHANGHAI_TZ = ZoneInfo(SCHEDULER_TIMEZONE)

_LOCK = threading.RLock()
_SCHEDULER: Any | None = None


def _now() -> datetime:
    return datetime.now(_SHANGHAI_TZ)


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="seconds") if value else ""


def _load_runtime_file(root: str | Path = ".") -> dict[str, Any]:
    path = Path(root) / RUNTIME_STATUS_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_runtime_file(payload: dict[str, Any], root: str | Path = ".") -> None:
    path = Path(root) / RUNTIME_STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_ranking_signal_date(output_dir: str | Path = "outputs") -> str:
    """读取当前排名文件的信号日期，不跨日期猜测。"""

    path = Path(output_dir) / "ranking_latest.csv"
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            first = next(reader, None) or {}
        return str(first.get("date") or first.get("signal_date") or "")[:10]
    except Exception:
        return ""


def expected_signal_date(now: datetime | None = None) -> str:
    value = get_latest_trading_day(now or _now())
    return value.strftime("%Y-%m-%d")


def _scheduler_config() -> dict[str, Any]:
    config = load_local_config()
    return {
        "enabled": bool(config.get("auto_retrain_enabled")),
        "hour": max(0, min(23, int(config.get("auto_retrain_hour") or 20))),
        "minute": max(0, min(59, int(config.get("auto_retrain_minute") or 0))),
        "catch_up": bool(config.get("auto_retrain_catch_up", True)),
    }


def _should_catch_up(config: dict[str, Any], now: datetime | None = None) -> bool:
    if not config.get("enabled") or not config.get("catch_up"):
        return False

    now = now or _now()
    expected = expected_signal_date(now)
    actual = read_ranking_signal_date()
    if actual == expected:
        return False

    expected_date = datetime.strptime(expected, "%Y-%m-%d").date()
    if expected_date < now.date():
        return True

    plan = now.replace(
        hour=int(config["hour"]),
        minute=int(config["minute"]),
        second=0,
        microsecond=0,
    )
    return now >= plan


def _write_running_state(*, source: str, started_at: datetime) -> None:
    current = _load_runtime_file()
    current.update(
        {
            "runtime_running": True,
            "last_started_at": _iso(started_at),
            "last_source": source,
            "last_status": "running",
            "last_error": "",
        }
    )
    _save_runtime_file(current)


def _run_configured_job(source: str = "scheduled") -> dict[str, Any]:
    started_at = _now()
    _write_running_state(source=source, started_at=started_at)
    try:
        from scheduler.daily_worker import run_scheduled_daily_update

        trade_date = expected_signal_date(started_at)
        result = run_scheduled_daily_update(
            trade_date=trade_date,
            user_ids=None,
            force=False,
            dry_run=False,
            skip_training=False,
            skip_news=False,
            skip_paper_trading=False,
            source=source,
            top_k=50,
            output_dir="outputs",
            db_path=None,
            root=".",
        )
        payload = result.to_dict()
        runtime = _load_runtime_file()
        runtime.update(
            {
                "runtime_running": True,
                "last_finished_at": _iso(_now()),
                "last_status": str(payload.get("overall_status") or "unknown"),
                "last_trade_date": str(payload.get("trade_date") or trade_date),
                "last_error": "\n".join(payload.get("warnings") or [])[:2000],
            }
        )
        _save_runtime_file(runtime)
        return payload
    except Exception as exc:
        runtime = _load_runtime_file()
        runtime.update(
            {
                "runtime_running": True,
                "last_finished_at": _iso(_now()),
                "last_status": "failed",
                "last_error": f"{type(exc).__name__}: {exc}"[:2000],
            }
        )
        _save_runtime_file(runtime)
        raise


def start_runtime_scheduler() -> Any | None:
    """随 FastAPI 启动常驻调度器；测试环境默认禁用真实任务。"""

    global _SCHEDULER
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if str(os.environ.get("STOCK_APP_RUNTIME_SCHEDULER_ENABLED", "1")).strip() in {
        "0",
        "false",
        "False",
    }:
        return None

    with _LOCK:
        if _SCHEDULER is None:
            try:
                from apscheduler.schedulers.background import BackgroundScheduler
            except ImportError as exc:
                runtime = _load_runtime_file()
                runtime.update(
                    {
                        "runtime_running": False,
                        "last_status": "failed",
                        "last_error": f"APScheduler unavailable: {exc}",
                    }
                )
                _save_runtime_file(runtime)
                return None
            _SCHEDULER = BackgroundScheduler(timezone=SCHEDULER_TIMEZONE)
            _SCHEDULER.start()
        reload_runtime_scheduler()
        return _SCHEDULER


def reload_runtime_scheduler() -> dict[str, Any]:
    """重新读取本地配置并更新 Cron，不把 Token 固化到 Job 参数中。"""

    with _LOCK:
        scheduler = _SCHEDULER
        config = _scheduler_config()
        if scheduler is None:
            return scheduler_public_status()

        for job_id in (SCHEDULER_JOB_ID, CATCH_UP_JOB_ID):
            existing = scheduler.get_job(job_id)
            if existing:
                scheduler.remove_job(job_id)

        if config["enabled"]:
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.date import DateTrigger

            scheduler.add_job(
                _run_configured_job,
                trigger=CronTrigger(
                    hour=int(config["hour"]),
                    minute=int(config["minute"]),
                    timezone=SCHEDULER_TIMEZONE,
                ),
                kwargs={"source": "scheduled"},
                id=SCHEDULER_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=997200,
            )
            if _should_catch_up(config):
                scheduler.add_job(
                    _run_configured_job,
                    trigger=DateTrigger(
                        run_date=_now() + timedelta(seconds=5),
                        timezone=SCHEDULER_TIMEZONE,
                    ),
                    kwargs={"source": "catch_up"},
                    id=CATCH_UP_JOB_ID,
                    replace_existing=True,
                    max_instances=1,
                    misfire_grace_time=997200,
                )

        status = scheduler_public_status()
        _save_runtime_file({**_load_runtime_file(), **status})
        return status


def shutdown_runtime_scheduler() -> None:
    global _SCHEDULER
    with _LOCK:
        if _SCHEDULER is not None:
            _SCHEDULER.shutdown(wait=False)
            _SCHEDULER = None
        runtime = _load_runtime_file()
        runtime["runtime_running"] = False
        runtime["next_run_time"] = ""
        _save_runtime_file(runtime)


def scheduler_public_status() -> dict[str, Any]:
    config = _scheduler_config()
    latest_job = load_latest_job_status(".")
    runtime = _load_runtime_file()
    scheduler = _SCHEDULER
    cron_job = scheduler.get_job(SCHEDULER_JOB_ID) if scheduler else None
    next_run = getattr(cron_job, "next_run_time", None)
    expected = expected_signal_date()
    signal_date = read_ranking_signal_date()

    return {
        "enabled": bool(config["enabled"]),
        "hour": int(config["hour"]),
        "minute": int(config["minute"]),
        "timezone": SCHEDULER_TIMEZONE,
        "catch_up": bool(config["catch_up"]),
        "runtime_running": bool(scheduler and scheduler.running),
        "job_registered": bool(cron_job),
        "next_run_time": _iso(next_run),
        "expected_signal_date": expected,
        "latest_signal_date": signal_date,
        "stale": bool(expected and signal_date != expected),
        "last_started_at": str(runtime.get("last_started_at") or latest_job.get("started_at") or ""),
        "last_finished_at": str(runtime.get("last_finished_at") or latest_job.get("finished_at") or ""),
        "last_trade_date": str(runtime.get("last_trade_date") or latest_job.get("trade_date") or ""),
        "last_status": str(runtime.get("last_status") or latest_job.get("overall_status") or "unknown"),
        "current_step": str(latest_job.get("current_step") or ""),
        "last_error": str(runtime.get("last_error") or "")[:2000],
    }


__all__ = [
    "expected_signal_date",
    "read_ranking_signal_date",
    "reload_runtime_scheduler",
    "scheduler_public_status",
    "shutdown_runtime_scheduler",
    "start_runtime_scheduler",
]
