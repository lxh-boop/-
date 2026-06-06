from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import CONFIDENCE_HIGH_THRESHOLD, CONFIDENCE_MEDIUM_THRESHOLD


CONFIDENCE_COMPONENT_WEIGHTS = {
    "probability_strength_component": 0.30,
    "ranking_position_component": 0.20,
    "calibration_quality_component": 0.20,
    "risk_penalty_component": 0.20,
    "volatility_penalty_component": 0.10,
}


def _numeric(series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(default)


def _rank01(series: pd.Series, ascending: bool = True, default: float = 0.5) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    if values.notna().sum() < 2 or values.nunique(dropna=True) < 2:
        return pd.Series(default, index=series.index, dtype=float)

    return values.rank(pct=True, ascending=ascending).fillna(default).astype(float)


def _calibration_quality(calibration_report: dict | None) -> float:
    if not calibration_report:
        return 0.45

    if not calibration_report.get("calibrated", False):
        return 0.40

    brier = calibration_report.get("brier")

    if brier is None:
        return 0.65

    try:
        return float(np.clip(1.0 - float(brier) / 0.25, 0.0, 1.0))
    except Exception:
        return 0.65


def _confidence_level(score: pd.Series) -> pd.Series:
    values = pd.to_numeric(score, errors="coerce").fillna(0.0)

    return pd.Series(
        np.where(
            values >= CONFIDENCE_HIGH_THRESHOLD,
            "高",
            np.where(values >= CONFIDENCE_MEDIUM_THRESHOLD, "中", "低"),
        ),
        index=score.index,
    )


def add_confidence_scores(
    df: pd.DataFrame,
    calibration_report: dict | None = None,
) -> pd.DataFrame:
    out = df.copy()

    if out.empty:
        out["confidence_score"] = []
        out["confidence"] = []
        out["confidence_detail"] = []
        return out

    prob_col = "up_prob_calibrated" if "up_prob_calibrated" in out.columns else "up_prob"
    prob = _numeric(out.get(prob_col, 0.5), default=0.5).clip(0.0, 1.0)
    score = _numeric(out.get("score", 0.5), default=0.5).clip(0.0, 1.0)
    risk_score = _numeric(out.get("risk_score", 0.5), default=0.5).clip(0.0, 1.0)
    vol = _numeric(out.get("vol_20", 0.0), default=0.0)

    components = pd.DataFrame(index=out.index)
    components["probability_strength_component"] = ((prob - 0.5).abs() * 2.0).clip(0.0, 1.0)
    components["ranking_position_component"] = ((score - 0.5).abs() * 2.0).clip(0.0, 1.0)
    components["calibration_quality_component"] = _calibration_quality(calibration_report)
    components["risk_penalty_component"] = (1.0 - risk_score).clip(0.0, 1.0)
    components["volatility_penalty_component"] = (1.0 - _rank01(vol, ascending=True)).clip(0.0, 1.0)

    confidence_score = pd.Series(0.0, index=out.index, dtype=float)

    for col, weight in CONFIDENCE_COMPONENT_WEIGHTS.items():
        confidence_score += components[col] * float(weight)

    out["confidence_score"] = confidence_score.clip(0.0, 1.0)
    out["confidence"] = _confidence_level(out["confidence_score"])

    details = []
    for idx in out.index:
        detail = {
            "confidence_score": round(float(out.at[idx, "confidence_score"]), 6),
            "probability_column": prob_col,
            "thresholds": {
                "high": CONFIDENCE_HIGH_THRESHOLD,
                "medium": CONFIDENCE_MEDIUM_THRESHOLD,
            },
            "components": {
                col: round(float(components.at[idx, col]), 6)
                for col in components.columns
            },
            "weights": CONFIDENCE_COMPONENT_WEIGHTS,
            "calibration_report": calibration_report or {"calibrated": False},
        }
        details.append(json.dumps(detail, ensure_ascii=False))

    out["confidence_detail"] = details
    return out
