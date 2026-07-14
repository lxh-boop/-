from scheduler.job_state import load_latest_job_status, run_recorded_step, save_job_status
from scheduler.schemas import JobStatus, SchedulerStatus


def test_job_state_save_and_load(tmp_path) -> None:
    status = JobStatus(job_id="daily_update_2026-06-11", run_id="run1", trade_date="2026-06-11")
    status.overall_status = SchedulerStatus.SUCCESS
    status.finished_at = "2026-06-11 18:00:00"

    save_job_status(status, root=tmp_path)

    loaded = load_latest_job_status(root=tmp_path)
    assert loaded["job_id"] == "daily_update_2026-06-11"
    assert loaded["overall_status"] == SchedulerStatus.SUCCESS
    assert (tmp_path / "runtime" / "jobs" / "history").exists()


def test_run_recorded_step_success_and_failure(tmp_path) -> None:
    status = JobStatus(job_id="job", run_id="run", trade_date="2026-06-11")

    result = run_recorded_step(
        status,
        "ok_step",
        lambda: {"status": SchedulerStatus.SUCCESS, "metadata": {"rows": 3}},
        root=tmp_path,
    )

    assert result["status"] == SchedulerStatus.SUCCESS
    assert "ok_step" in status.completed_steps
    assert status.step_status["ok_step"].metadata["rows"] == 3

    failed = run_recorded_step(
        status,
        "bad_step",
        lambda: {"status": SchedulerStatus.FAILED, "error_message": "boom"},
        root=tmp_path,
        allow_failure=True,
    )

    assert failed["status"] == SchedulerStatus.FAILED
    assert "bad_step" in status.failed_steps
