from __future__ import annotations

import pandas as pd

from kronos_runtime.ranking import build_kronos_ranking
from kronos_runtime.settings import KRONOS_MODEL_NAME


def test_original_kronos_ranking_has_no_sentiment_adjustment(tmp_path) -> None:
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
                "kronos_oriented_score": 1.0,
                "kronos_raw_score": -1.0,
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
                "pred_return": 0.01,
                "kronos_oriented_score": 0.5,
                "kronos_raw_score": -0.5,
            },
        ]
    )

    ranking, report = build_kronos_ranking(
        predictions=predictions,
        feature_data=pd.DataFrame(),
        history_dir=str(tmp_path),
    )

    assert ranking["rank"].tolist() == [1, 2]
    assert ranking["kronos_score"].tolist() == ranking["score"].tolist()
    assert set(ranking["model_name"]) == {KRONOS_MODEL_NAME}
    assert not any("moneyflow" in column for column in ranking.columns)
    assert report["sentiment_fusion"] is False
