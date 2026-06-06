from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


UNIVARIATE_RETURN_COL = "close_ret_1"
MULTIVARIATE_OHLCV_COLUMNS = [
    "close_ret_1",
    "open_ret_1",
    "high_rel_close",
    "low_rel_close",
    "vwap_rel_close",
    "volume_log_chg",
    "amount_log_chg",
    "pct_chg_decimal",
]


@dataclass
class WindowBatch:
    rows: list[dict]
    windows: list[np.ndarray]
    feature_columns: list[str]


def _safe_numeric(series: pd.Series, default: float = 0.0) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(default)


def normalize_ohlcv_frame(raw_data: pd.DataFrame) -> pd.DataFrame:
    if raw_data is None or raw_data.empty:
        raise RuntimeError("raw_data is required for OHLCV time-series model adapters.")

    data = raw_data.copy()
    required = ["date", "code", "close"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise RuntimeError(f"raw_data is missing required columns: {missing}")

    data["date"] = pd.to_datetime(data["date"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    if "name" not in data.columns:
        data["name"] = data["code"]

    for col in ["open", "high", "low", "close", "volume", "amount", "vwap", "pct_chg"]:
        if col not in data.columns:
            data[col] = np.nan
        data[col] = _safe_numeric(data[col], default=np.nan)

    data["open"] = data["open"].fillna(data["close"])
    data["high"] = data["high"].fillna(data[["open", "close"]].max(axis=1))
    data["low"] = data["low"].fillna(data[["open", "close"]].min(axis=1))
    data["vwap"] = data["vwap"].fillna(data["close"])
    data["volume"] = data["volume"].fillna(0.0).clip(lower=0.0)
    data["amount"] = data["amount"].fillna(0.0).clip(lower=0.0)
    data["pct_chg"] = data["pct_chg"].fillna(0.0)

    data = data.dropna(subset=["date", "code", "close"])
    data = data.sort_values(["code", "date"]).reset_index(drop=True)
    return data


def add_ohlcv_features(raw_data: pd.DataFrame) -> pd.DataFrame:
    data = normalize_ohlcv_frame(raw_data)
    out_parts = []

    for _, group in data.groupby("code", sort=False):
        g = group.sort_values("date").copy()
        close = g["close"].replace(0, np.nan)

        g["close_ret_1"] = close.pct_change()
        g["open_ret_1"] = g["open"].replace(0, np.nan).pct_change()
        g["high_rel_close"] = g["high"] / close - 1.0
        g["low_rel_close"] = g["low"] / close - 1.0
        g["vwap_rel_close"] = g["vwap"] / close - 1.0
        g["volume_log_chg"] = np.log1p(g["volume"]).diff()
        g["amount_log_chg"] = np.log1p(g["amount"]).diff()
        g["pct_chg_decimal"] = g["pct_chg"] / 100.0

        for col in MULTIVARIATE_OHLCV_COLUMNS:
            g[col] = (
                pd.to_numeric(g[col], errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
                .clip(-0.2, 0.2)
            )
        out_parts.append(g)

    return pd.concat(out_parts, ignore_index=True) if out_parts else data


def build_windows(
    raw_data: pd.DataFrame,
    prediction_dates: Iterable,
    context_length: int,
    min_context: int,
    feature_columns: list[str],
) -> WindowBatch:
    data = add_ohlcv_features(raw_data)
    prediction_date_set = set(pd.to_datetime(list(prediction_dates)))
    context_length = int(context_length)
    min_context = int(min_context)

    rows: list[dict] = []
    windows: list[np.ndarray] = []

    for _, group in data.groupby("code", sort=False):
        group = group.sort_values("date").reset_index(drop=True)
        for idx, row in group.iterrows():
            date_value = pd.to_datetime(row["date"])
            if date_value not in prediction_date_set:
                continue

            start = max(0, idx - context_length + 1)
            window = group.iloc[start : idx + 1]
            if len(window) < min_context:
                continue

            values = (
                window[feature_columns]
                .replace([np.inf, -np.inf], np.nan)
                .fillna(0.0)
                .astype(np.float32)
                .to_numpy()
            )
            rows.append(
                {
                    "date": date_value,
                    "code": row["code"],
                    "name": row.get("name", row["code"]),
                    "close": row["close"],
                }
            )
            windows.append(values)

    return WindowBatch(rows=rows, windows=windows, feature_columns=list(feature_columns))


def compound_return_from_forecast(values, horizon: int = 5, clip: float = 0.2) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    arr = arr[:, : int(horizon)]
    arr = np.nan_to_num(arr, nan=0.0, posinf=clip, neginf=-clip)
    arr = np.clip(arr, -clip, clip)
    return np.prod(1.0 + arr, axis=1) - 1.0
