from scheduler.job_state import save_job_status
from scheduler.schemas import JobStatus, SchedulerStatus

from app.classic_services import load_scheduler_status_summary, read_scheduler_log_tail


def test_app_loads_scheduler_status_summary(tmp_path) -> None:
    status = JobStatus(job_id="daily_update_2026-06-11", run_id="run1", trade_date="2026-06-11")
    status.overall_status = SchedulerStatus.SUCCESS
    status.recommendation_count = 7
    status.paper_order_count = 2
    status.finished_at = "2026-06-11 18:00:00"
    save_job_status(status, root=tmp_path)

    summary = load_scheduler_status_summary(root=tmp_path)

    assert summary["is_available"] is True
    assert summary["overall_status"] == SchedulerStatus.SUCCESS
    assert summary["recommendation_count"] == 7
    assert summary["paper_order_count"] == 2


def test_app_reads_latest_scheduler_log_tail(tmp_path, monkeypatch) -> None:
    log_dir = tmp_path / "logs" / "scheduler"
    log_dir.mkdir(parents=True)
    (log_dir / "daily_worker_20260611.log").write_text("first\nsecond\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert read_scheduler_log_tail(max_chars=20).endswith("second\n")
