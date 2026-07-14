from __future__ import annotations

from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_missing_ai_adjustment_holds_positions(tmp_path) -> None:
    write_stage5q_inputs(tmp_path)
    for path in (tmp_path / "users" / "u1" / "recommendations").glob("final_recommendations_*.csv"):
        path.unlink()
    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        dry_run=True,
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
    )
    assert result.missing_ai_adjustment_days == ["2026-04-01"]
    assert result.skipped_days == 1
