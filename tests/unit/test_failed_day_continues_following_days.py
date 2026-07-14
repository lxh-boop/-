from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_failed_day_continues_following_days(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    write_stage5q_inputs(tmp_path, trade_date="2026-04-02", count=30)
    (tmp_path / "users" / "u1" / "recommendations" / "final_recommendations_20260401.csv").unlink()

    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-02",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        audit_log="required",
        continue_on_error=True,
    )

    assert result.completed_days == 2
    assert result.failed_continue_day_count == 1
    assert len(list((Path(result.audit_log_dir) / "daily").glob("*.json"))) == 2
