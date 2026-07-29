from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_FILES = (
    "scheduler/runtime_scheduler.py",
    "scheduler/daily_worker.py",
    "server/api/main.py",
    "application/web_settings_service.py",
    "frontend/src/components/dashboard/SchedulerStatusPanel.tsx",
    "frontend/src/pages/dashboard/SettingsPage.tsx",
    "scripts/run_scheduled_daily_update.bat",
)


def main() -> int:
    violations: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            violations.append(f"missing:{relative}")

    if not violations:
        runtime = (ROOT / "scheduler/runtime_scheduler.py").read_text(encoding="utf-8")
        daily = (ROOT / "scheduler/daily_worker.py").read_text(encoding="utf-8")
        api = (ROOT / "server/api/main.py").read_text(encoding="utf-8")
        settings = (ROOT / "application/web_settings_service.py").read_text(encoding="utf-8")
        bat = (ROOT / "scripts/run_scheduled_daily_update.bat").read_text(
            encoding="utf-8", errors="ignore"
        )

        checks = {
            "api_lifespan_scheduler": "start_runtime_scheduler" in api and "shutdown_runtime_scheduler" in api,
            "market_update_before_user_tasks": '"market_update"' in daily and "run_market_update_from_local_config" in daily,
            "config_reload": "reload_runtime_scheduler" in settings,
            "catch_up": "auto_retrain_catch_up" in runtime,
            "no_job_secret_capture": "kwargs={\"source\"" in runtime and "tushare_token" not in runtime,
            "windows_python": ".venv\\Scripts\\python.exe" in bat and ".venv1" not in bat,
        }
        violations.extend(name for name, passed in checks.items() if not passed)

    payload = {
        "stage": "6.7",
        "violations": violations,
        "violation_count": len(violations),
        "checked_files": len(REQUIRED_FILES),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
