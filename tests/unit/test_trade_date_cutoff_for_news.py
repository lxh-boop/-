from __future__ import annotations

from database.repositories.news_repository import assign_news_trade_date


TRADING_DAYS = [
    "2026-06-08",
    "2026-06-09",
    "2026-06-10",
    "2026-06-11",
    "2026-06-12",
    "2026-06-15",
]


def test_before_cutoff_news_belongs_to_same_trading_day() -> None:
    assert assign_news_trade_date("2026-06-09 10:30:00", TRADING_DAYS) == "2026-06-09"


def test_after_cutoff_news_belongs_to_next_trading_day() -> None:
    assert assign_news_trade_date("2026-06-09 18:30:00", TRADING_DAYS) == "2026-06-10"


def test_non_trading_day_news_belongs_to_next_trading_day() -> None:
    assert assign_news_trade_date("2026-06-13 09:30:00", TRADING_DAYS) == "2026-06-15"


def test_exact_cutoff_is_not_same_day_to_avoid_future_news() -> None:
    assert assign_news_trade_date("2026-06-09 15:00:00", TRADING_DAYS) == "2026-06-10"
