from __future__ import annotations

import pandas as pd

import kronos_runtime.ranking as ranking_module
from kronos_runtime.ranking import build_kronos_ranking
from kronos_runtime.settings import KRONOS_MODEL_NAME


def test_target_mode_kronos_ranking_uses_validation_selected_signal_without_sentiment(tmp_path) -> None:
    predictions = pd.DataFrame(
        [
            {
                "date": "2026-07-31",
                "prediction_date": "2026-08-03",
                "code": "000001",
                "name": "甲",
                "close": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
                "pct_chg": 0.0,
                "ret_5": 0.0,
                "ret_20": 0.0,
                "vol_20": 0.01,
                "drawdown_20": 0.0,
                "pred_return": 0.01,
                "pred_open": 10.0,
                "pred_high": 10.2,
                "pred_low": 9.9,
                "pred_close": 10.1,
                "target_ranking_signal": 0.2,
                "target_confidence": 0.55,
            },
            {
                "date": "2026-07-31",
                "prediction_date": "2026-08-03",
                "code": "000002",
                "name": "乙",
                "close": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
                "pct_chg": 0.0,
                "ret_5": 0.0,
                "ret_20": 0.0,
                "vol_20": 0.01,
                "drawdown_20": 0.0,
                "pred_return": -0.02,
                "pred_open": 9.9,
                "pred_high": 10.0,
                "pred_low": 9.7,
                "pred_close": 9.8,
                "target_ranking_signal": -0.1,
                "target_confidence": 0.48,
            },
        ]
    )

    ranking, report = build_kronos_ranking(
        predictions=predictions,
        feature_data=pd.DataFrame(),
        history_dir=str(tmp_path),
    )

    assert ranking["rank"].tolist() == [1, 2]
    assert ranking["code"].tolist() == ["000001", "000002"]
    assert ranking["expected_next_day_return"].tolist() == [0.01, -0.02]
    assert ranking["predicted_up_first"].tolist() == [True, False]
    assert not any("kronos_score" in column for column in ranking.columns)
    assert set(ranking["model_name"]) == {KRONOS_MODEL_NAME}
    assert not any("moneyflow" in column for column in ranking.columns)
    assert report["ranking_head_used"] is False
    assert report["ranking_head_trained_but_not_selected"] is True
    assert report["ranking_orientation"] == "causal_stock_hit_rate_descending"
    assert report["ranking_basis"] == "daily_fixed_top15_by_predicted_next_day_return"
    assert ranking["top15_up_signal"].tolist() == [True, True]
    assert report["native_output"][:4] == ["pred_open", "pred_high", "pred_low", "pred_close"]
    assert report["sentiment_fusion"] is False


def test_fixed_top15_order_does_not_use_historical_hit_rate(
    tmp_path,
    monkeypatch,
) -> None:
    predictions = pd.DataFrame(
        [
            {
                "date": "2026-07-31",
                "prediction_date": "2026-08-03",
                "code": code,
                "name": code,
                "close": 10.0,
                "amount": 1000.0,
                "volume": 100.0,
                "pct_chg": 0.0,
                "ret_5": 0.0,
                "ret_20": 0.0,
                "vol_20": 0.01,
                "drawdown_20": 0.0,
                "pred_return": 0.01,
                "pred_open": 10.0,
                "pred_high": 10.2,
                "pred_low": 9.9,
                "pred_close": 10.1,
                "target_ranking_signal": signal,
                "target_confidence": 0.55,
            }
            for code, signal in (
                ("000001", -0.9),
                ("000002", 0.5),
                ("000003", 0.0),
            )
        ]
    )

    def fake_calibration(frame, **_kwargs):
        out = frame.copy()
        out["up_prob_calibrated"] = out["code"].map(
            {"000001": 0.4, "000002": 0.8, "000003": 0.8}
        )
        out["calibration_sample_count"] = out["code"].map(
            {"000001": 10, "000002": 2, "000003": 5}
        )
        out["calibration_positive_count"] = out["code"].map(
            {"000001": 4, "000002": 2, "000003": 4}
        )
        out["calibrated"] = True
        out["calibration_method"] = "empirical_stock_predicted_up_next_day_hit_rate"
        report = {"calibrated": True}
        out.attrs["probability_calibration"] = report
        return out, report

    monkeypatch.setattr(
        ranking_module,
        "ensure_kronos_validation_history",
        lambda _history_dir: {"ready": True},
    )
    monkeypatch.setattr(
        ranking_module,
        "calibrate_ranking_probabilities",
        fake_calibration,
    )

    ranking, _ = build_kronos_ranking(
        predictions=predictions,
        feature_data=pd.DataFrame(),
        history_dir=str(tmp_path),
    )

    assert ranking["code"].tolist() == ["000001", "000002", "000003"]
    assert ranking["top15_up_signal"].tolist() == [True, True, True]
    assert ranking["up_prob_calibrated"].tolist() == [0.4, 0.8, 0.8]
    assert ranking["calibration_sample_count"].tolist() == [10, 2, 5]
