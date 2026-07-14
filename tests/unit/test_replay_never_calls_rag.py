from __future__ import annotations

import pipelines.paper_backfill_pipeline as backfill
from stage5q_helpers import write_stage5q_inputs


def test_replay_never_calls_rag(tmp_path, monkeypatch) -> None:
    write_stage5q_inputs(tmp_path)
    monkeypatch.setattr(backfill, "build_final_recommendations", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rag/signal path")))
    result = backfill.run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        dry_run=True,
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        disable_rag=True,
    )
    assert result.failed_days == 0
