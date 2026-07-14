from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


DEFAULT_TASK_NAME = "StockDailyApp-AutoUpdate"
DEFAULT_TRIGGER_TIME = "17:30"


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def detect_project_python(root: str | Path | None = None) -> Path:
    root_path = Path(root) if root else project_root()
    venv_python = root_path / ".venv1" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def scheduled_update_bat_path(root: str | Path | None = None) -> Path:
    return (Path(root) if root else project_root()) / "scripts" / "run_scheduled_daily_update.bat"


def build_schtasks_create_command(
    task_name: str = DEFAULT_TASK_NAME,
    trigger_time: str = DEFAULT_TRIGGER_TIME,
    root: str | Path | None = None,
    run_level: str = "LIMITED",
) -> list[str]:
    script = scheduled_update_bat_path(root)
    return [
        "schtasks",
        "/Create",
        "/TN",
        task_name,
        "/TR",
        str(script),
        "/SC",
        "DAILY",
        "/ST",
        trigger_time,
        "/F",
        "/RL",
        run_level,
    ]


def task_install_summary(
    task_name: str = DEFAULT_TASK_NAME,
    trigger_time: str = DEFAULT_TRIGGER_TIME,
    root: str | Path | None = None,
    run_level: str = "LIMITED",
) -> dict[str, Any]:
    root_path = Path(root) if root else project_root()
    return {
        "task_name": task_name,
        "trigger_time": trigger_time,
        "python": str(detect_project_python(root_path)),
        "script_path": str(scheduled_update_bat_path(root_path)),
        "working_directory": str(root_path),
        "run_level": run_level,
        "create_command": build_schtasks_create_command(task_name, trigger_time, root_path, run_level),
    }
