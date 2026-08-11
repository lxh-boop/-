from __future__ import annotations

import numpy as np
import pandas as pd

from confidence_scoring import add_confidence_scores
from kronos_runtime.calibration_history import ensure_kronos_validation_history
from kronos_runtime.settings import (
    KRONOS_BACKEND,
    KRONOS_MODEL_NAME,
    KRONOS_MODEL_VERSION,
    KRONOS_RANKING_ORIENTATION,
)
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
    target_signal = pd.to_numeric(out["target_ranking_signal"], errors="coerce")
    if target_signal.isna().any():
        raise RuntimeError("Kronos 目标模式排序信号存在空值")
    if KRONOS_RANKING_ORIENTATION != "causal_stock_hit_rate_descending":
        raise RuntimeError(f"不支持的 Kronos 目标模式方向：{KRONOS_RANKING_ORIENTATION}")
    out["predicted_up_first"] = expected_return.gt(0.0)
    out["target_order_score"] = -target_signal
    out = out.sort_values(
        ["predicted_up_first", "expected_next_day_return", "code"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    out["score"] = (len(out) - out.index.to_numpy(dtype=float)) / max(len(out), 1)
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
    calibration_history = ensure_kronos_validation_history(history_dir)
    out, calibration_report = calibrate_ranking_probabilities(
        out,
        feature_data=feature_data,
        history_dir=history_dir,
        model_name=KRONOS_MODEL_NAME,
        model_version=KRONOS_MODEL_VERSION,
    )
    out = out.sort_values(
        ["predicted_up_first", "expected_next_day_return", "code"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    out["rank"] = np.arange(1, len(out) + 1)
    out["score"] = (len(out) - out.index.to_numpy(dtype=float)) / max(len(out), 1)
    out["top15_up_signal"] = out["rank"].le(15)
    out = add_confidence_scores(out, calibration_report=calibration_report)
    out = normalize_ranking_columns(out)
    validate_ranking_schema(out)
    out.attrs["probability_calibration"] = calibration_report
    ranking_report = {
        "source": "kronos_mini_next_day_ohlcva",
        "native_output": ["pred_open", "pred_high", "pred_low", "pred_close", "pred_volume", "pred_amount"],
        "ranking_basis": "daily_fixed_top15_by_predicted_next_day_return",
        "ranking_head_used": False,
        "ranking_head_trained_but_not_selected": True,
        "ranking_orientation": KRONOS_RANKING_ORIENTATION,
        "sentiment_fusion": False,
        "top15_selection": {
            "fixed_daily_count": 15,
            "stock_direction_head_used": False,
            "reason": "candidate_stock_direction_heads_failed_55pct_holdout_acceptance",
        },
        "training_penalty_note": (
            "4/6/9/12/16 false-positive penalties remain training-only and use realized T+1 labels; "
            "no same-day sentiment adjustment is applied."
        ),
        "calibration_history": calibration_history,
    }
    return out, ranking_report
