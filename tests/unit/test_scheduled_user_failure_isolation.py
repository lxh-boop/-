from scheduler.daily_worker import run_scheduled_daily_update
from scheduler.schemas import SchedulerStatus


def test_user_failure_does_not_stop_other_users(tmp_path) -> None:
    def user_runner(**kwargs):
        if kwargs["user_id"] == "bad":
            raise RuntimeError("user failed")
        return {"status": SchedulerStatus.SUCCESS, "recommendation_count": 1}

    result = run_scheduled_daily_update(
        trade_date="2026-06-11",
        user_ids=["ok", "bad"],
        root=tmp_path,
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        public_task_runner=lambda **_: {"status": SchedulerStatus.SUCCESS},
        user_task_runner=user_runner,
    )

    assert result.overall_status == SchedulerStatus.PARTIAL_SUCCESS
    assert result.user_task_status["ok"]["status"] == SchedulerStatus.SUCCESS
    assert result.user_task_status["bad"]["status"] == SchedulerStatus.FAILED
    assert result.recommendation_count == 1
