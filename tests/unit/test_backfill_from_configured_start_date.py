from pipelines.paper_backfill_pipeline import resolve_backfill_start_date


def test_backfill_from_configured_start_date() -> None:
    assert resolve_backfill_start_date("2026-04-01") >= "2026-04-01"

