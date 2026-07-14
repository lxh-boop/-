from pipelines.backfill_state import BackfillState, load_backfill_state, save_backfill_state
from pipelines.paper_backfill_pipeline import run_paper_trading_backfill


def test_backfill_resume_skips_completed_days(tmp_path) -> None:
    state = BackfillState(user_id="u1", start_date="2026-04-01", end_date="2026-04-01")
    state.completed_days = ["2026-04-01"]
    save_backfill_state(state, output_dir=tmp_path)

    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-01",
        output_dir=tmp_path,
        db_path=tmp_path / "db.sqlite",
        dry_run=True,
        resume=True,
    )

    loaded = load_backfill_state("u1", output_dir=tmp_path)
    assert result.completed_days == 1
    assert loaded is not None
    assert loaded.completed_days == ["2026-04-01"]
