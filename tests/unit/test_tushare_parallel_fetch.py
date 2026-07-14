from __future__ import annotations

import threading
import time

import pandas as pd

import data_tushare


class _SharedFakeTushare:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active_daily_calls = 0
        self.max_active_daily_calls = 0

    def trade_cal(self, **kwargs):
        _ = kwargs
        return pd.DataFrame(
            {
                "cal_date": ["20260101", "20260102", "20260103", "20260104"],
                "is_open": ["1", "1", "1", "1"],
            }
        )

    def daily(self, trade_date: str, fields: str):
        _ = fields
        with self.lock:
            self.active_daily_calls += 1
            self.max_active_daily_calls = max(self.max_active_daily_calls, self.active_daily_calls)
        try:
            time.sleep(0.05)
            return pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "trade_date": trade_date,
                        "open": 10,
                        "high": 11,
                        "low": 9,
                        "close": 10.5,
                        "pct_chg": 1.0,
                        "vol": 1000,
                        "amount": 1050,
                    },
                    {
                        "ts_code": "600000.SH",
                        "trade_date": trade_date,
                        "open": 20,
                        "high": 21,
                        "low": 19,
                        "close": 20.5,
                        "pct_chg": 1.5,
                        "vol": 2000,
                        "amount": 4100,
                    },
                ]
            )
        finally:
            with self.lock:
                self.active_daily_calls -= 1

    def daily_basic(self, trade_date: str, fields: str):
        _ = fields
        return pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": trade_date, "turnover_rate": 0.8},
                {"ts_code": "600000.SH", "trade_date": trade_date, "turnover_rate": 1.2},
            ]
        )


def test_fetch_stock_pool_recent_daily_fast_runs_trade_dates_in_parallel(monkeypatch) -> None:
    fake = _SharedFakeTushare()
    monkeypatch.setattr(data_tushare, "init_tushare_pro", lambda token=None: fake)

    df = data_tushare.fetch_stock_pool_recent_daily_fast(
        token="test-token",
        stock_pool={"000001": "Ping An Bank", "600000": "Shanghai Pudong"},
        recent_trade_days=4,
        end_date="20260104",
        include_turnover=True,
        max_workers=4,
        sleep_seconds=0,
    )

    assert fake.max_active_daily_calls > 1
    assert len(df) == 8
    assert sorted(df["code"].unique().tolist()) == ["000001", "600000"]
    assert df["date"].nunique() == 4
    assert "turnover" in df.columns
