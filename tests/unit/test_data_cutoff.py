from datetime import datetime

import pandas as pd

from data_tushare import resolve_daily_data_end_date


class FakePro:
    def trade_cal(self, **kwargs):
        end_date = kwargs["end_date"]
        all_dates = ["20260603", "20260604", "20260605"]
        usable = [d for d in all_dates if d <= end_date]
        return pd.DataFrame({"cal_date": usable, "is_open": ["1"] * len(usable)})


def test_resolve_daily_data_end_date_before_close_uses_previous_trade_day():
    end_date, message = resolve_daily_data_end_date(
        FakePro(),
        now=datetime(2026, 6, 5, 14, 30),
    )

    assert end_date == "20260604"
    assert "上一已完成交易日" in message


def test_resolve_daily_data_end_date_after_close_can_use_today():
    end_date, message = resolve_daily_data_end_date(
        FakePro(),
        now=datetime(2026, 6, 5, 16, 0),
    )

    assert end_date == "20260605"
    assert "今日收盘" in message


def test_resolve_daily_data_end_date_respects_explicit_end_date():
    end_date, message = resolve_daily_data_end_date(
        FakePro(),
        end_date="2026-06-03",
        now=datetime(2026, 6, 5, 16, 0),
    )

    assert end_date == "20260603"
    assert "用户指定" in message
