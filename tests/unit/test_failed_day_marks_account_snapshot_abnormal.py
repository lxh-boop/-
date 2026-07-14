import json

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_failed_day_marks_account_snapshot_abnormal(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    for path in (tmp_path / "users" / "u1" / "recommendations").glob("final_recommendations_*.csv"):
        path.unlink()

    run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        audit_log="required",
        continue_on_error=True,
    )

    account = json.loads((tmp_path / "portfolio" / "u1" / "history" / "accounts" / "account_20260401.json").read_text(encoding="utf-8"))
    assert account["daily_replay_status"] == "failed_continue"
    assert account["abnormal_snapshot"] == 1
