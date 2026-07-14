import json
from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_daily_audit_log_contains_sources(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
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
    payload = json.loads(next((Path(result.audit_log_dir) / "daily").glob("*.json")).read_text(encoding="utf-8"))
    assert payload["sources"]["original_ranking_file_path"]
    assert payload["sources"]["ai_adjustment_file_path"]
    assert payload["validation"]["original_ranking_count"] == 30
