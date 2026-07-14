from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from config import AGENT_QUANT_DB_PATH
from database.connection import initialize_database
from scheduler.job_state import load_latest_job_status
from scheduler.trading_calendar import get_latest_trading_day, is_trading_day


def run_health_check(
    root: str | Path = ".",
    db_path: str | Path | None = AGENT_QUANT_DB_PATH,
) -> dict[str, Any]:
    root_path = Path(root)
    checks: dict[str, Any] = {
        "python": sys.executable,
        "root": str(root_path.resolve()),
        "app_exists": (root_path / "app.py").exists(),
        "scheduler_package_exists": (root_path / "scheduler").exists(),
        "run_script_exists": (root_path / "scripts" / "run_scheduled_daily_update.bat").exists(),
        "latest_status_exists": bool(load_latest_job_status(root_path)),
    }
    try:
        db_file = initialize_database(db_path)
        checks["database_ok"] = True
        checks["database_path"] = str(db_file)
    except Exception as exc:
        checks["database_ok"] = False
        checks["database_error"] = str(exc)
    try:
        latest = get_latest_trading_day(None)
        checks["calendar_ok"] = True
        checks["latest_trading_day"] = latest.strftime("%Y-%m-%d")
        checks["today_is_trading_day"] = is_trading_day(None)
    except Exception as exc:
        checks["calendar_ok"] = False
        checks["calendar_error"] = str(exc)
    checks["overall_status"] = "success" if checks.get("app_exists") and checks.get("database_ok") and checks.get("calendar_ok") else "failed"
    return checks
