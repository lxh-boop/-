from __future__ import annotations

import pandas as pd

from app.services.backtest_display import build_display_date_options, is_prediction_only_date


def test_latest_prediction_date_is_inserted_before_backtest_dates():
    trades = pd.DataFrame({"date": ["2026-06-03", "2026-06-02"]})
    ranking = pd.DataFrame({"date": ["2026-06-04"], "code": ["000001"]})
    options, latest = build_display_date_options(trades, ranking)
    assert latest == "2026-06-04"
    assert options[0] == "2026-06-04"
    assert options[1:] == ["2026-06-03", "2026-06-02"]


def test_prediction_only_date_detection():
    trades = pd.DataFrame({"date": ["2026-06-03"]})
    assert is_prediction_only_date("2026-06-04", trades)
    assert not is_prediction_only_date("2026-06-03", trades)
