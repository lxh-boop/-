from __future__ import annotations

from datetime import datetime

import pandas as pd

from data_tushare import build_market_data_window


class FakePro:
    def trade_cal(self, exchange, start_date, end_date, is_open, fields):
        open_dates = [
            "20260601",
            "20260602",
            "20260603",
            "20260604",
            "20260605",
            "20260608",
        ]
        rows = [
            {"cal_date": date, "is_open": "1"}
            for date in open_dates
            if start_date <= date <= end_date
        ]
        return pd.DataFrame(rows)


def test_weekend_uses_latest_trade_day_and_next_open_day():
    info = build_market_data_window(FakePro(), now=datetime(2026, 6, 6, 10, 0))

    assert info["data_status"] == "non_trading_day"
    assert info["expected_signal_date"] == "2026-06-05"
    assert info["prediction_target_date"] == "2026-06-08"


def test_trading_day_before_ready_uses_previous_trade_day():
    info = build_market_data_window(FakePro(), now=datetime(2026, 6, 5, 10, 0))

    assert info["data_status"] == "before_close_or_data_ready"
    assert info["expected_signal_date"] == "2026-06-04"
    assert info["prediction_target_date"] == "2026-06-05"


def test_trading_day_after_ready_expects_today_data():
    info = build_market_data_window(FakePro(), now=datetime(2026, 6, 5, 16, 0))

    assert info["data_status"] == "after_close_expect_today"
    assert info["expected_signal_date"] == "2026-06-05"
    assert info["prediction_target_date"] == "2026-06-08"
