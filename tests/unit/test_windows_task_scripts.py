from pathlib import Path

from scheduler.windows_task_installer import DEFAULT_TASK_NAME, build_schtasks_create_command, task_install_summary


def test_windows_task_command_uses_project_script(tmp_path) -> None:
    command = build_schtasks_create_command(root=tmp_path, trigger_time="17:30")

    assert command[:2] == ["schtasks", "/Create"]
    assert DEFAULT_TASK_NAME in command
    assert str(tmp_path / "scripts" / "run_scheduled_daily_update.bat") in command
    assert "17:30" in command


def test_windows_task_scripts_are_present_and_call_scheduler_cli() -> None:
    root = Path(__file__).resolve().parents[2]
    bat = root / "scripts" / "run_scheduled_daily_update.bat"
    install = root / "scripts" / "install_windows_daily_task.ps1"
    uninstall = root / "scripts" / "uninstall_windows_daily_task.ps1"

    assert bat.exists()
    assert install.exists()
    assert uninstall.exists()
    assert "scheduler.scheduler_cli run" in bat.read_text(encoding="utf-8", errors="ignore")
    assert "Register-ScheduledTask" in install.read_text(encoding="utf-8", errors="ignore")
    assert "Unregister-ScheduledTask" in uninstall.read_text(encoding="utf-8", errors="ignore")


def test_task_install_summary_contains_no_password_fields(tmp_path) -> None:
    summary = task_install_summary(root=tmp_path)

    assert summary["task_name"] == DEFAULT_TASK_NAME
    assert "password" not in " ".join(map(str, summary.values())).lower()
