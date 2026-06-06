from __future__ import annotations

import json

import numpy as np
import pandas as pd

from config import MODEL_NAME, MODEL_PRED_COL


REQUIRED_RANKING_COLUMNS = [
    "rank",
    "date",
    "code",
    "name",
    "close",
    "pred_5d_ret",
    "raw_score",
    "up_prob",
    "up_prob_calibrated",
    "score",
    "confidence_score",
    "confidence",
    "risk_score",
    "risk_level",
    "risk_detail",
    "confidence_detail",
    "model_name",
    "ret_5",
    "ret_20",
    "vol_20",
    "drawdown_20",
]


def normalize_ranking_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    if out.empty:
        for col in REQUIRED_RANKING_COLUMNS:
            if col not in out.columns:
                out[col] = []
        return out

    if "code" in out.columns:
        out["code"] = out["code"].astype(str).str.zfill(6)

    if "raw_score" not in out.columns:
        if MODEL_PRED_COL in out.columns:
            out["raw_score"] = pd.to_numeric(out[MODEL_PRED_COL], errors="coerce")
        elif "pred_5d_ret" in out.columns:
            out["raw_score"] = pd.to_numeric(out["pred_5d_ret"], errors="coerce")
        else:
            out["raw_score"] = 0.0

    if "pred_5d_ret" not in out.columns:
        out["pred_5d_ret"] = pd.to_numeric(out["raw_score"], errors="coerce").fillna(0.0)

    if "up_prob" not in out.columns:
        out["up_prob"] = 0.5

    if "up_prob_calibrated" not in out.columns:
        out["up_prob_calibrated"] = out["up_prob"]

    if "score" not in out.columns:
        out["score"] = pd.to_numeric(out["raw_score"], errors="coerce").rank(pct=True)

    if "rank" not in out.columns:
        out = out.sort_values("score", ascending=False).reset_index(drop=True)
        out.insert(0, "rank", np.arange(1, len(out) + 1))

    defaults = {
        "date": "",
        "name": "",
        "close": np.nan,
        "confidence_score": np.nan,
        "confidence": "未知",
        "risk_score": np.nan,
        "risk_level": "未知",
        "risk_detail": "{}",
        "confidence_detail": "{}",
        "model_name": MODEL_NAME,
        "ret_5": np.nan,
        "ret_20": np.nan,
        "vol_20": np.nan,
        "drawdown_20": np.nan,
    }

    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default

    numeric_cols = [
        "close",
        "pred_5d_ret",
        "raw_score",
        "up_prob",
        "up_prob_calibrated",
        "score",
        "confidence_score",
        "risk_score",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
    ]

    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["up_prob"] = out["up_prob"].fillna(0.5).clip(0.0, 1.0)
    out["up_prob_calibrated"] = out["up_prob_calibrated"].fillna(out["up_prob"]).clip(0.0, 1.0)
    out["score"] = out["score"].fillna(0.5).clip(0.0, 1.0)

    for detail_col in ["risk_detail", "confidence_detail"]:
        out[detail_col] = out[detail_col].map(
            lambda x: x if isinstance(x, str) and x.strip() else json.dumps({}, ensure_ascii=False)
        )

    return out


def validate_ranking_schema(df: pd.DataFrame) -> None:
    missing = [col for col in REQUIRED_RANKING_COLUMNS if col not in df.columns]

    if missing:
        raise ValueError(f"ranking 缺少必要字段：{missing}")

    if df.empty:
        raise ValueError("ranking 为空。")

    if df["code"].isna().any():
        raise ValueError("ranking 中存在空股票代码。")

    if df["rank"].isna().any():
        raise ValueError("ranking 中存在空排名。")
