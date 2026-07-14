from pipelines.paper_backfill_pipeline import trading_days_between


def test_backfill_uses_real_trading_days() -> None:
    assert trading_days_between("2026-04-01", "2026-04-07") == [
        "2026-04-01",
        "2026-04-02",
        "2026-04-03",
        "2026-04-07",
    ]
