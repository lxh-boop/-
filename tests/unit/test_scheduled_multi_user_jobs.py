from scheduler.daily_worker import run_scheduled_daily_update
from scheduler.schemas import SchedulerStatus


def test_scheduled_worker_aggregates_multiple_user_outputs(tmp_path) -> None:
    def public_runner(**_):
        return {"status": SchedulerStatus.SUCCESS, "metadata": {"ranking_output_path": "ranking.csv"}}

    def user_runner(**kwargs):
        return {
            "status": SchedulerStatus.SUCCESS,
            "recommendation_count": 2,
            "paper_order_count": 1 if kwargs["user_id"] == "u1" else 0,
            "position_count": 1,
        }

    result = run_scheduled_daily_update(
        trade_date="2026-06-11",
        user_ids=["u1", "u2"],
        root=tmp_path,
        output_dir=tmp_path / "outputs",
        db_path=tmp_path / "agent.db",
        public_task_runner=public_runner,
        user_task_runner=user_runner,
    )

    assert result.overall_status == SchedulerStatus.SUCCESS
    assert set(result.user_task_status) == {"u1", "u2"}
    assert result.recommendation_count == 4
    assert result.paper_order_count == 1
