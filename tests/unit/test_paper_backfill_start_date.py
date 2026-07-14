from config import DEFAULT_PAPER_TRADING_START_DATE
from pipelines.paper_backfill_pipeline import resolve_backfill_start_date


def test_default_paper_backfill_start_date_is_20260401() -> None:
    assert DEFAULT_PAPER_TRADING_START_DATE == "2026-04-01"
    assert resolve_backfill_start_date() == "2026-04-01"


def test_non_trading_start_date_moves_to_next_trading_day() -> None:
    assert resolve_backfill_start_date("2026-04-04") == "2026-04-07"
