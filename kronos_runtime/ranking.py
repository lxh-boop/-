from __future__ import annotations

import numpy as np
import pandas as pd

from confidence_scoring import add_confidence_scores
from kronos_runtime.settings import KRONOS_BACKEND, KRONOS_MODEL_NAME
from ranking_probability_calibration import calibrate_ranking_probabilities
from ranking_schema import normalize_ranking_columns, validate_ranking_schema
from risk_scoring import add_risk_scores


def build_kronos_ranking(
    *,
    predictions: pd.DataFrame,
    feature_data: pd.DataFrame,
    history_dir: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if predictions.empty:
        raise RuntimeError("Kronos 没有生成预测")
    out = predictions.copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    expected_return = pd.to_numeric(out["pred_return"], errors="coerce")
    if expected_return.isna().any():
        raise RuntimeError("Kronos 下一交易日预测收益存在空值")
    out["expected_next_day_return"] = expected_return
    out["score"] = expected_return.rank(method="average", pct=True).clip(0.0, 1.0)
    out = out.sort_values(["expected_next_day_return", "code"], ascending=[False, True]).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    out["raw_score"] = out["expected_next_day_return"]
    out["pred_score"] = out["expected_next_day_return"]
    out["pred_5d_ret"] = out["pred_return"]
    # The ranking head confidence is not a calibrated probability. A neutral
    # placeholder is kept until archived top-15 outcomes can calibrate it.
    out["up_prob"] = 0.5
    out["up_prob_calibrated"] = np.nan
    out["model_name"] = KRONOS_MODEL_NAME
    out["model_backend"] = KRONOS_BACKEND

    out = add_risk_scores(out)
    out, calibration_report = calibrate_ranking_probabilities(
        out,
        feature_data=feature_data,
        history_dir=history_dir,
        model_name=KRONOS_MODEL_NAME,
    )
    out = add_confidence_scores(out, calibration_report=calibration_report)
    out = normalize_ranking_columns(out)
    validate_ranking_schema(out)
    out.attrs["probability_calibration"] = calibration_report
    ranking_report = {
        "source": "kronos_mini_next_day_ohlcva",
        "native_output": ["pred_open", "pred_high", "pred_low", "pred_close", "pred_volume", "pred_amount"],
        "ranking_basis": "pred_close / current_close - 1",
        "ranking_head_used": False,
        "sentiment_fusion": False,
        "training_penalty_note": (
            "3/5/8 false-positive penalties remain training-only and use realized T+1 labels; "
            "no same-day sentiment adjustment is applied."
        ),
    }
    return out, ranking_report
