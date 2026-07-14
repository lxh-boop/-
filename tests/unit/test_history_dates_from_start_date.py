from pipelines.paper_backfill_pipeline import trading_days_between


def test_history_dates_from_start_date() -> None:
    days = trading_days_between("2026-04-01", "2026-04-10")

    assert days
    assert min(days) >= "2026-04-01"

