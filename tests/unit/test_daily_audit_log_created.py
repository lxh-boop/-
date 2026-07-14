from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_daily_audit_log_created(tmp_path) -> None:
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

    root = Path(result.audit_log_dir)
    assert result.daily_audit_json_count == 1
    assert result.daily_audit_markdown_count == 1
    assert list((root / "daily").glob("*.json"))
    assert list((root / "human_readable").glob("*.md"))
