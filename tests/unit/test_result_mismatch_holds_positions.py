from __future__ import annotations

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_rank_field_mismatch_does_not_break_stock_code_merge(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, mismatch=True)
    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        dry_run=True,
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
    )
    assert result.result_mismatch_days == []
    assert result.skipped_days == 0
