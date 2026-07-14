import json

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_missing_daily_result_fails_replay(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    for path in (tmp_path / "users" / "u1" / "recommendations").glob("final_recommendations_*.csv"):
        path.unlink()

    result = run_paper_trading_backfill(
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

    assert result.missing_ai_adjustment_days == ["2026-04-01"]
    assert result.failed_continue_day_count == 1
    daily = json.loads((tmp_path.parent / "missing").read_text()) if False else None
    assert daily is None
    audit_file = next((__import__("pathlib").Path(result.audit_log_dir) / "daily").glob("*.json"))
    payload = json.loads(audit_file.read_text(encoding="utf-8"))
    assert payload["status"] == "failed_continue"
    assert payload["continue_policy"]["strategy_trading_disabled"] is True
