import pandas as pd

from scheduler.daily_worker import run_public_daily_tasks
from scheduler.schemas import SchedulerStatus


def test_public_daily_task_runs_once_per_trade_date(tmp_path) -> None:
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    pd.DataFrame([{"code": "000001", "score": 0.8}]).to_csv(output_dir / "ranking_latest.csv", index=False)

    first = run_public_daily_tasks("2026-06-11", output_dir=output_dir, db_path=tmp_path / "missing.db", root=tmp_path)
    second = run_public_daily_tasks("2026-06-11", output_dir=output_dir, db_path=tmp_path / "missing.db", root=tmp_path)

    assert first["status"] == SchedulerStatus.SUCCESS
    assert second["status"] == SchedulerStatus.SKIPPED
    assert (output_dir / "shared" / "ranking_latest.csv").exists()
