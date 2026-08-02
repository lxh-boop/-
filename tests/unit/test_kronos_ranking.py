from __future__ import annotations

import pandas as pd

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
    assert report["ranking_head_used"] is True
    assert report["ranking_orientation"] == "ascending"
    assert report["ranking_basis"] == "predicted_up_first_then_target_mode_signal_ascending"
    assert report["native_output"][:4] == ["pred_open", "pred_high", "pred_low", "pred_close"]
    assert report["sentiment_fusion"] is False
