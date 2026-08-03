from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from kronos_runtime.settings import (
    KRONOS_BACKEND,
    KRONOS_MODEL_NAME,
    KRONOS_MODEL_VERSION,
    test_predictions_path,
    validation_predictions_path,
)


def ensure_kronos_validation_history(history_dir: str | Path) -> dict[str, Any]:
    """Expose the leakage-free Kronos validation predictions to calibration.

    The lab artifact contains one point-in-time prediction and its realized T+1
    return for every stock/date in the unseen validation window.  It is copied
    into the application's standard prediction-history format so the generic
    incremental calibrator can combine it with future daily ranking archives.
    """

    source_paths = (validation_predictions_path(), test_predictions_path())
    missing_sources = [str(path) for path in source_paths if not path.exists()]
    if missing_sources:
        return {
            "ready": False,
            "reason": "validation_predictions_missing",
            "missing_sources": missing_sources,
        }

    source = pd.concat(
        [pd.read_parquet(path) for path in source_paths],
        ignore_index=True,
        sort=False,
    )
    required = {
        "trade_date",
        "stock_code",
        "pred_return",
        "ranking_score",
        "real_return",
    }
    missing = sorted(required - set(source.columns))
    if missing:
        raise RuntimeError(f"Kronos 校准历史缺少字段：{missing}")

    history = source.loc[:, sorted(required)].copy()
    history["date"] = pd.to_datetime(
        history["trade_date"].astype(str),
        format="%Y%m%d",
        errors="coerce",
    ).dt.strftime("%Y-%m-%d")
    history["code"] = history["stock_code"].astype(str).str.extract(
        r"(\d{6})",
        expand=False,
    )
    for column in ("pred_return", "ranking_score", "real_return"):
        history[column] = pd.to_numeric(history[column], errors="coerce")
    history = history.dropna(
        subset=["date", "code", "pred_return", "ranking_score", "real_return"]
    )
    history = history.sort_values(["date", "code"]).drop_duplicates(
        ["date", "code"], keep="last"
    )
    history["predicted_up_first"] = history["pred_return"].gt(0.0)
    history = history.sort_values(
        ["date", "predicted_up_first", "ranking_score", "code"],
        ascending=[True, False, True, True],
        kind="stable",
    ).reset_index(drop=True)
    history["rank"] = history.groupby("date", sort=False).cumcount() + 1
    daily_size = history.groupby("date", sort=False)["code"].transform("size")
    history["score"] = (daily_size - history["rank"] + 1) / daily_size
    history["up_prob"] = np.where(history["predicted_up_first"], 1.0, 0.0)
    history["future_1d_ret"] = history["real_return"]
    history["model_name"] = KRONOS_MODEL_NAME
    history["model_backend"] = KRONOS_BACKEND
    history["model_version"] = KRONOS_MODEL_VERSION

    output_path = (
        Path(history_dir)
        / "backtests"
        / "predictions"
        / f"target_full_recent_v1_{KRONOS_MODEL_NAME}_t1_predictions.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "date",
        "code",
        "rank",
        "score",
        "up_prob",
        "pred_return",
        "predicted_up_first",
        "future_1d_ret",
        "model_name",
        "model_backend",
        "model_version",
    ]
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    history.loc[:, columns].to_csv(
        temporary_path,
        index=False,
        encoding="utf-8-sig",
    )
    os.replace(temporary_path, output_path)
    return {
        "ready": True,
        "sources": [str(path) for path in source_paths],
        "output": str(output_path),
        "rows": int(len(history)),
        "dates": int(history["date"].nunique()),
        "start_date": str(history["date"].min()),
        "end_date": str(history["date"].max()),
    }
