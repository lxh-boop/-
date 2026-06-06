from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_engine import run_topk_backtest
from scripts.evaluate.run_model_backtest import build_daily_returns, normalize_predictions


def test_backtest_engine_rebalances_every_holding_period(sample_prediction_df, tmp_path):
    daily, metrics = run_topk_backtest(
        sample_prediction_df,
        model_name="unit_model",
        topk=1,
        holding_days=5,
        buy_cost=0.0,
        sell_cost=0.0,
        stamp_tax=0.0,
        output_dir=tmp_path,
    )
    assert daily["date"].tolist() == ["2026-01-01", "2026-01-06"]
    assert np.isclose(daily.loc[0, "gross_return"], 0.10)
    assert np.isclose(daily.loc[1, "nav"], 1.21)
    assert metrics["num_days"] == 2


def test_unified_backtest_does_not_compound_5d_return_daily(sample_prediction_df):
    daily = build_daily_returns(
        pred=sample_prediction_df,
        run_id="run",
        model_name="unit_model",
        model_source="local",
        model_category="A",
        topk=1,
        holding_days=5,
        rank_by="score",
        cost_rate=0.0,
    )
    assert len(daily) == 2
    assert daily["date"].tolist() == ["2026-01-01", "2026-01-06"]
    assert np.isclose(daily["nav"].iloc[-1], 1.21)
    assert not np.isclose(daily["nav"].iloc[-1], 1.10**10)


def test_benchmark_uses_same_holding_period(sample_prediction_df):
    daily = build_daily_returns(
        pred=sample_prediction_df,
        run_id="run",
        model_name="unit_model",
        model_source="local",
        model_category="A",
        topk=1,
        holding_days=5,
        rank_by="score",
        cost_rate=0.0,
    )
    expected_benchmark = (0.10 + 0.05 - 0.02) / 3
    assert np.isclose(daily.loc[0, "benchmark_return"], expected_benchmark)
    assert np.isclose(daily.loc[1, "benchmark_return"], expected_benchmark)


def test_turnover_cost_is_applied_on_rebalance_only(sample_prediction_df):
    daily = build_daily_returns(
        pred=sample_prediction_df,
        run_id="run",
        model_name="unit_model",
        model_source="local",
        model_category="A",
        topk=1,
        holding_days=5,
        rank_by="score",
        cost_rate=0.01,
    )
    assert np.isclose(daily.loc[0, "cost"], 0.01)
    assert np.isclose(daily.loc[1, "cost"], 0.0)
    assert np.isclose(daily.loc[0, "net_return"], 0.09)


def test_holding_one_uses_t1_return_not_future_5d_return():
    pred = pd.DataFrame(
        [
            {"date": "2026-01-01", "code": "000001", "name": "A", "close": 10.0, "pred_5d_ret": 0.9, "raw_score": 0.9, "score": 0.9, "future_5d_ret": 0.50},
            {"date": "2026-01-02", "code": "000001", "name": "A", "close": 11.0, "pred_5d_ret": 0.9, "raw_score": 0.9, "score": 0.9, "future_5d_ret": 0.50},
            {"date": "2026-01-01", "code": "000002", "name": "B", "close": 20.0, "pred_5d_ret": 0.1, "raw_score": 0.1, "score": 0.1, "future_5d_ret": 0.50},
            {"date": "2026-01-02", "code": "000002", "name": "B", "close": 18.0, "pred_5d_ret": 0.1, "raw_score": 0.1, "score": 0.1, "future_5d_ret": 0.50},
        ]
    )
    pred = normalize_predictions(pred, model_name="unit_model", rank_by="score")

    daily = build_daily_returns(
        pred=pred,
        run_id="run",
        model_name="unit_model",
        model_source="local",
        model_category="A",
        topk=1,
        holding_days=1,
        rank_by="score",
        cost_rate=0.0,
    )

    assert len(daily) == 1
    assert np.isclose(daily.loc[0, "gross_return"], 0.10)
    assert not np.isclose(daily.loc[0, "gross_return"], 0.50)


def test_topk_rebalance_sells_dropouts_and_buys_new_entries():
    pred = pd.DataFrame(
        [
            {"date": "2026-01-01", "code": "000001", "name": "A", "close": 10.0, "pred_5d_ret": 0.9, "raw_score": 0.9, "score": 0.9, "future_5d_ret": 0.0},
            {"date": "2026-01-01", "code": "000002", "name": "B", "close": 20.0, "pred_5d_ret": 0.1, "raw_score": 0.1, "score": 0.1, "future_5d_ret": 0.0},
            {"date": "2026-01-02", "code": "000001", "name": "A", "close": 10.5, "pred_5d_ret": 0.1, "raw_score": 0.1, "score": 0.1, "future_5d_ret": 0.0},
            {"date": "2026-01-02", "code": "000002", "name": "B", "close": 21.0, "pred_5d_ret": 0.9, "raw_score": 0.9, "score": 0.9, "future_5d_ret": 0.0},
            {"date": "2026-01-03", "code": "000001", "name": "A", "close": 11.0, "pred_5d_ret": 0.1, "raw_score": 0.1, "score": 0.1, "future_5d_ret": 0.0},
            {"date": "2026-01-03", "code": "000002", "name": "B", "close": 22.0, "pred_5d_ret": 0.9, "raw_score": 0.9, "score": 0.9, "future_5d_ret": 0.0},
        ]
    )
    pred = normalize_predictions(pred, model_name="unit_model", rank_by="score")

    daily = build_daily_returns(
        pred=pred,
        run_id="run",
        model_name="unit_model",
        model_source="local",
        model_category="A",
        topk=1,
        holding_days=1,
        rank_by="score",
        cost_rate=0.01,
    )

    assert daily.loc[0, "bought_codes"] == "000001"
    assert daily.loc[0, "sold_codes"] == ""
    assert np.isclose(daily.loc[0, "buy_turnover"], 1.0)
    assert np.isclose(daily.loc[0, "sell_turnover"], 0.0)
    assert np.isclose(daily.loc[0, "cost"], 0.01)
    assert daily.loc[1, "bought_codes"] == "000002"
    assert daily.loc[1, "sold_codes"] == "000001"
    assert np.isclose(daily.loc[1, "buy_turnover"], 1.0)
    assert np.isclose(daily.loc[1, "sell_turnover"], 1.0)
    assert np.isclose(daily.loc[1, "cost"], 0.02)


def test_daily_returns_has_required_columns(sample_daily_returns_df):
    required = {
        "date",
        "run_id",
        "model_name",
        "topk",
        "holding_days",
        "gross_return",
        "net_return",
        "cum_return",
        "nav",
        "benchmark_return",
    }
    assert required.issubset(sample_daily_returns_df.columns)
    assert np.isclose(sample_daily_returns_df["cum_return"].iloc[-1], sample_daily_returns_df["nav"].iloc[-1] - 1.0)
