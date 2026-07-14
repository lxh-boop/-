from datetime import date

from scheduler.trading_calendar import get_latest_trading_day, get_next_trading_day, is_trading_day, parse_date


def test_parse_date_accepts_common_formats() -> None:
    assert parse_date("2026-06-11") == date(2026, 6, 11)
    assert parse_date("20260611") == date(2026, 6, 11)
    assert parse_date("2026/06/11") == date(2026, 6, 11)


def test_weekend_and_holiday_are_not_trading_days() -> None:
    assert is_trading_day("2026-06-13") is False
    assert is_trading_day("2026-01-01") is False


def test_latest_and_next_trading_day_skip_weekend() -> None:
    assert get_latest_trading_day("2026-06-13") == date(2026, 6, 12)
    assert get_next_trading_day("2026-06-13") == date(2026, 6, 15)
