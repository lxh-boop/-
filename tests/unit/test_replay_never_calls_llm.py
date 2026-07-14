from __future__ import annotations

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_replay_never_calls_llm(tmp_path) -> None:
    write_stage5q_inputs(tmp_path)
    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        dry_run=True,
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        disable_llm=True,
    )
    assert result.stored_only_mode is True
    assert result.failed_days == 0
