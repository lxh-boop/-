from __future__ import annotations

from pathlib import Path

from scheduler.daily_worker import run_scheduled_daily_update
from scheduler.schemas import SchedulerStatus


def test_market_update_runs_before_public_and_user_tasks(tmp_path) -> None:
    order: list[str] = []

    def market_runner(**kwargs):
        order.append("market")
        assert kwargs["trade_date"] == "2026-07-27"
        return {
            "status": SchedulerStatus.SUCCESS,
            "metadata": {"signal_date": "2026-07-27"},
        }

    def public_runner(**kwargs):
        order.append("public")
        return {
            "status": SchedulerStatus.SUCCESS,
            "metadata": {
                "ranking_output_path": "outputs/shared/ranking_latest.csv",
                "signal_date": "2026-07-27",
            },
        }

    def user_runner(**kwargs):
        order.append(f"user:{kwargs['user_id']}")
        return {"status": SchedulerStatus.SUCCESS}

    result = run_scheduled_daily_update(
        trade_date="2026-07-27",
        user_ids=["cht"],
        root=tmp_path,
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        market_update_runner=market_runner,
        public_task_runner=public_runner,
        user_task_runner=user_runner,
    )

    assert result.overall_status == SchedulerStatus.SUCCESS
    assert result.latest_signal_date == "2026-07-27"
    assert order == ["market", "public", "user:cht"]


def test_injected_public_runner_keeps_legacy_tests_offline(tmp_path) -> None:
    called: list[str] = []

    result = run_scheduled_daily_update(
        trade_date="2026-07-27",
        user_ids=["u1"],
        root=tmp_path,
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        public_task_runner=lambda **_: {
            "status": SchedulerStatus.SUCCESS,
            "metadata": {},
        },
        user_task_runner=lambda **_: called.append("user") or {
            "status": SchedulerStatus.SUCCESS
        },
    )

    assert result.overall_status == SchedulerStatus.SUCCESS
    assert "market_update" not in result.step_status
    assert called == ["user"]


def test_fastapi_hosts_the_scheduler_and_windows_fallback_uses_dot_venv() -> None:
    root = Path(__file__).resolve().parents[2]
    api_source = (root / "server" / "api" / "main.py").read_text(encoding="utf-8")
    bat_source = (root / "scripts" / "run_scheduled_daily_update.bat").read_text(
        encoding="utf-8", errors="ignore"
    )
    runtime_source = (root / "scheduler" / "runtime_scheduler.py").read_text(
        encoding="utf-8"
    )

    assert "start_runtime_scheduler" in api_source
    assert "shutdown_runtime_scheduler" in api_source
    assert ".venv\\Scripts\\python.exe" in bat_source
    assert ".venv1" not in bat_source
    assert "auto_retrain_catch_up" in runtime_source
    assert "run_scheduled_daily_update" in runtime_source


def test_settings_surface_contains_real_scheduler_controls() -> None:
    root = Path(__file__).resolve().parents[2]
    page = (root / "frontend" / "src" / "pages" / "dashboard" / "SettingsPage.tsx").read_text(
        encoding="utf-8"
    )
    panel = (root / "frontend" / "src" / "components" / "dashboard" / "SchedulerStatusPanel.tsx").read_text(
        encoding="utf-8"
    )

    for marker in (
        "scheduler_enabled",
        "scheduler_hour",
        "scheduler_minute",
        "scheduler_catch_up",
    ):
        assert marker in page
    assert "立即运行完整日更" in panel
    assert "expected_signal_date" in panel
    assert "latest_signal_date" in panel
