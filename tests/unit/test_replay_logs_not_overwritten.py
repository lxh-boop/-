from pathlib import Path

from pipelines.paper_backfill_pipeline import run_paper_trading_backfill
from stage5q_helpers import write_stage5q_inputs


def test_replay_logs_not_overwritten(tmp_path) -> None:
    write_stage5q_inputs(tmp_path, trade_date="2026-04-01", count=30)
    kwargs = dict(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
        force=True,
        use_stored_ranking_only=True,
        use_stored_ai_adjustment_only=True,
        audit_log="required",
        continue_on_error=True,
    )

    first = run_paper_trading_backfill(**kwargs)
    second = run_paper_trading_backfill(**kwargs)

    assert first.run_id != second.run_id
    assert Path(first.audit_log_dir).exists()
    assert Path(second.audit_log_dir).exists()
