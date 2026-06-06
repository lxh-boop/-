from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_metrics import calc_annual_return, calc_max_drawdown, calc_sharpe, calc_win_rate


def test_cum_return_equals_nav_minus_one(sample_daily_returns_df):
    assert np.allclose(sample_daily_returns_df["cum_return"], sample_daily_returns_df["nav"] - 1.0)


def test_max_drawdown_is_non_positive():
    nav = pd.Series([1.0, 1.2, 1.1, 1.3])
    assert calc_max_drawdown(nav) <= 0


def test_annual_return_positive_for_rising_nav():
    nav = pd.Series([1.0, 1.1, 1.21])
    assert calc_annual_return(nav, trading_days=252 / 5) > 0


def test_sharpe_handles_flat_returns():
    assert np.isnan(calc_sharpe(pd.Series([0.01]), trading_days=252))


def test_win_rate_uses_positive_returns_only():
    assert np.isclose(calc_win_rate(pd.Series([0.01, -0.01, 0.0])), 1 / 3)
