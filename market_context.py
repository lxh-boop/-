from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from config import (
    EPS,
    MARKET_CONTEXT_FEATURE_CACHE_PATH,
    MARKET_CONTEXT_FIT_END_DATE,
    MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH,
    MARKET_CONTEXT_START_DATE,
)
from data_tushare import init_tushare_pro


MARKET_CONTEXT_WINDOWS = [5, 10, 20, 30, 60]

# The external DFT_UNET checkpoint follows the MASTER market context order:
# CSI300, CSI500 and CSI800.
MARKET_INDEX_TS_CODES = {
    "SH000300": "000300.SH",
    "SH000905": "000905.SH",
    "SH000906": "000906.SH",
}


def build_market_context_columns() -> list[str]:
    columns: list[str] = []

    for index_code in MARKET_INDEX_TS_CODES:
        columns.append(f"market_{index_code}_ret_1")

        for window in MARKET_CONTEXT_WINDOWS:
            columns.extend(
                [
                    f"market_{index_code}_ret_mean_{window}",
                    f"market_{index_code}_ret_std_{window}",
                    f"market_{index_code}_amount_mean_ratio_{window}",
                    f"market_{index_code}_amount_std_ratio_{window}",
                ]
            )

    return columns


MARKET_CONTEXT_COLUMNS = build_market_context_columns()


def _parse_yyyymmdd(value) -> pd.Timestamp:
    text = str(value).strip()
    if not text:
        raise ValueError("date value is empty")
    if "-" in text:
        return pd.to_datetime(text)
    return pd.to_datetime(text, format="%Y%m%d")


def _to_yyyymmdd(value) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def _normalize_raw_index_data(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "index_code", "close", "amount"])

    data = df.copy()

    if "trade_date" in data.columns and "date" not in data.columns:
        data = data.rename(columns={"trade_date": "date"})

    if "ts_code" in data.columns and "index_code" not in data.columns:
        reverse_map = {v: k for k, v in MARKET_INDEX_TS_CODES.items()}
        data["index_code"] = data["ts_code"].map(reverse_map)

    if "amount" not in data.columns and "vol" in data.columns:
        data["amount"] = data["vol"]

    required = ["date", "index_code", "close", "amount"]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"market index data missing columns: {missing}")

    data = data[required].copy()
    data["date"] = pd.to_datetime(data["date"])
    data["index_code"] = data["index_code"].astype(str).str.upper()
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data["amount"] = pd.to_numeric(data["amount"], errors="coerce")

    data = data[data["index_code"].isin(MARKET_INDEX_TS_CODES.keys())].copy()
    data = data.dropna(subset=["date", "index_code", "close"])
    data["amount"] = data["amount"].fillna(0.0)
    data = data.drop_duplicates(subset=["index_code", "date"], keep="last")
    data = data.sort_values(["index_code", "date"]).reset_index(drop=True)
    return data


def _read_index_cache() -> pd.DataFrame:
    path = Path(MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH)
    if not path.exists():
        return pd.DataFrame(columns=["date", "index_code", "close", "amount"])

    data = pd.read_csv(path)
    return _normalize_raw_index_data(data)


def _write_index_cache(df: pd.DataFrame) -> None:
    path = Path(MARKET_CONTEXT_INDEX_DAILY_CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = _normalize_raw_index_data(df)
    out.to_csv(path, index=False, encoding="utf-8-sig")


def _index_cache_covers(df: pd.DataFrame, start_date: str, end_date: str) -> bool:
    if df is None or df.empty:
        return False

    start_dt = _parse_yyyymmdd(start_date)
    end_dt = _parse_yyyymmdd(end_date)

    for index_code in MARKET_INDEX_TS_CODES:
        group = df[df["index_code"] == index_code]
        if group.empty:
            return False
        if group["date"].min() > start_dt or group["date"].max() < end_dt:
            return False

    return True


def fetch_market_index_daily_tushare(
    token: str,
    start_date: str,
    end_date: str,
    max_retries: int = 3,
    sleep_seconds: float = 0.2,
) -> pd.DataFrame:
    if not token or not str(token).strip():
        raise RuntimeError(
            "External DFT_UNET 需要三个指数日线来生成市场上下文。"
            "本地缓存不完整，请先在左侧填写 Tushare Token 后再生成排名。"
        )

    pro = init_tushare_pro(token)
    frames = []

    for index_code, ts_code in MARKET_INDEX_TS_CODES.items():
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                df = pro.index_daily(
                    ts_code=ts_code,
                    start_date=start_date,
                    end_date=end_date,
                    fields="ts_code,trade_date,close,vol,amount",
                )

                if df is None or df.empty:
                    raise RuntimeError(f"Tushare index_daily returned empty data for {ts_code}")

                df["index_code"] = index_code
                frames.append(df)
                break
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    raise RuntimeError(
                        f"获取指数 {index_code}({ts_code}) 日线失败：{type(exc).__name__}: {exc}"
                    ) from exc
                time.sleep(1.0 + attempt * 0.5)

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    data = pd.concat(frames, ignore_index=True)
    return _normalize_raw_index_data(data)


def ensure_market_index_daily(
    token: str | None,
    start_date: str,
    end_date: str,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    cache = _read_index_cache()
    source = "cache"

    if force_refresh or not _index_cache_covers(cache, start_date, end_date):
        fetched = fetch_market_index_daily_tushare(
            token=token or "",
            start_date=start_date,
            end_date=end_date,
        )
        if cache.empty:
            cache = fetched
        else:
            cache = pd.concat([cache, fetched], ignore_index=True)
        cache = _normalize_raw_index_data(cache)
        _write_index_cache(cache)
        source = "tushare"

    report = {
        "source": source,
        "index_rows": int(len(cache)),
        "index_codes": list(MARKET_INDEX_TS_CODES.keys()),
        "index_date_min": str(cache["date"].min().date()) if not cache.empty else "",
        "index_date_max": str(cache["date"].max().date()) if not cache.empty else "",
    }
    return cache, report


def _robust_zscore_clip(
    df: pd.DataFrame,
    columns: list[str],
    fit_end_date: str = MARKET_CONTEXT_FIT_END_DATE,
    clip_value: float = 3.0,
) -> pd.DataFrame:
    out = df.copy()
    fit_end = _parse_yyyymmdd(fit_end_date)
    fit_mask = out["date"] <= fit_end
    fit = out.loc[fit_mask, columns]

    if fit.notna().sum().min() < 20:
        fit = out[columns]

    median = fit.median(skipna=True)
    mad = (fit - median).abs().median(skipna=True)
    scale = mad * 1.4826
    fallback_scale = fit.std(ddof=0, skipna=True)
    scale = scale.where(scale > EPS, fallback_scale)
    scale = scale.where(scale > EPS, 1.0)

    out[columns] = (out[columns] - median) / scale
    out[columns] = out[columns].clip(-clip_value, clip_value)
    return out


def compute_market_context_features(
    index_daily_df: pd.DataFrame,
    normalize: bool = True,
) -> pd.DataFrame:
    data = _normalize_raw_index_data(index_daily_df)
    if data.empty:
        raise RuntimeError("没有可用于生成 DFT_UNET 市场上下文的指数日线。")

    frames = []

    for index_code in MARKET_INDEX_TS_CODES:
        group = data[data["index_code"] == index_code].sort_values("date").copy()
        if group.empty:
            raise RuntimeError(f"缺少指数 {index_code} 的日线，无法生成 DFT_UNET 市场上下文。")

        close = group["close"].astype(float)
        amount = group["amount"].astype(float)
        ret_1 = close.pct_change(1)

        out = pd.DataFrame({"date": group["date"].values})
        out[f"market_{index_code}_ret_1"] = ret_1.values

        for window in MARKET_CONTEXT_WINDOWS:
            out[f"market_{index_code}_ret_mean_{window}"] = ret_1.rolling(window).mean().values
            out[f"market_{index_code}_ret_std_{window}"] = ret_1.rolling(window).std().values
            out[f"market_{index_code}_amount_mean_ratio_{window}"] = (
                amount.rolling(window).mean() / (amount + EPS)
            ).values
            out[f"market_{index_code}_amount_std_ratio_{window}"] = (
                amount.rolling(window).std() / (amount + EPS)
            ).values

        frames.append(out)

    context = frames[0]
    for frame in frames[1:]:
        context = context.merge(frame, on="date", how="outer")

    context = context.sort_values("date").reset_index(drop=True)
    context = context.replace([np.inf, -np.inf], np.nan)

    for col in MARKET_CONTEXT_COLUMNS:
        if col not in context.columns:
            context[col] = np.nan

    context = context[["date"] + MARKET_CONTEXT_COLUMNS].copy()

    if normalize:
        context = _robust_zscore_clip(context, MARKET_CONTEXT_COLUMNS)

    context[MARKET_CONTEXT_COLUMNS] = context[MARKET_CONTEXT_COLUMNS].fillna(0.0)
    return context


def _read_context_cache() -> pd.DataFrame:
    path = Path(MARKET_CONTEXT_FEATURE_CACHE_PATH)
    if not path.exists():
        return pd.DataFrame()

    data = pd.read_csv(path)
    if "date" not in data.columns:
        return pd.DataFrame()

    data["date"] = pd.to_datetime(data["date"])
    missing = [col for col in MARKET_CONTEXT_COLUMNS if col not in data.columns]
    if missing:
        return pd.DataFrame()

    return data[["date"] + MARKET_CONTEXT_COLUMNS].copy()


def _write_context_cache(df: pd.DataFrame) -> None:
    path = Path(MARKET_CONTEXT_FEATURE_CACHE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df[["date"] + MARKET_CONTEXT_COLUMNS].copy()
    out.to_csv(path, index=False, encoding="utf-8-sig")


def _context_cache_covers(df: pd.DataFrame, min_date: pd.Timestamp, max_date: pd.Timestamp) -> bool:
    if df is None or df.empty:
        return False
    if df["date"].min() > min_date or df["date"].max() < max_date:
        return False
    return True


def ensure_market_context_for_feature_data(
    feature_data: pd.DataFrame,
    token: str | None = None,
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if feature_data is None or feature_data.empty:
        raise RuntimeError("没有 Alpha158 特征数据，无法补齐 DFT_UNET 市场上下文。")
    if "date" not in feature_data.columns:
        raise RuntimeError("Alpha158 特征数据缺少 date 列，无法补齐 DFT_UNET 市场上下文。")

    data = feature_data.copy()
    data["date"] = pd.to_datetime(data["date"])
    min_date = data["date"].min()
    max_date = data["date"].max()

    context = _read_context_cache()
    index_report: dict[str, Any] = {"source": "market_context_cache"}

    if force_refresh or not _context_cache_covers(context, min_date, max_date):
        start_date = MARKET_CONTEXT_START_DATE
        end_date = _to_yyyymmdd(max_date)
        index_daily, index_report = ensure_market_index_daily(
            token=token,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
        context = compute_market_context_features(index_daily, normalize=True)
        _write_context_cache(context)

    context = context.sort_values("date").reset_index(drop=True)
    unique_dates = pd.DataFrame({"date": sorted(data["date"].dropna().unique())})
    aligned = pd.merge_asof(
        unique_dates.sort_values("date"),
        context[["date"] + MARKET_CONTEXT_COLUMNS].sort_values("date"),
        on="date",
        direction="backward",
    )

    missing_rows_before_fill = int(aligned[MARKET_CONTEXT_COLUMNS].isna().any(axis=1).sum())
    aligned[MARKET_CONTEXT_COLUMNS] = aligned[MARKET_CONTEXT_COLUMNS].bfill().fillna(0.0)

    data = data.drop(columns=[c for c in MARKET_CONTEXT_COLUMNS if c in data.columns])
    enriched = data.merge(aligned, on="date", how="left")
    enriched[MARKET_CONTEXT_COLUMNS] = enriched[MARKET_CONTEXT_COLUMNS].fillna(0.0)

    report = {
        "market_context_columns": len(MARKET_CONTEXT_COLUMNS),
        "market_indices": list(MARKET_INDEX_TS_CODES.keys()),
        "feature_date_min": str(min_date.date()),
        "feature_date_max": str(max_date.date()),
        "context_date_min": str(context["date"].min().date()) if not context.empty else "",
        "context_date_max": str(context["date"].max().date()) if not context.empty else "",
        "missing_date_rows_before_fill": missing_rows_before_fill,
        "normalization": "robust_zscore_clip",
        "fit_end_date": str(_parse_yyyymmdd(MARKET_CONTEXT_FIT_END_DATE).date()),
        "index_data": index_report,
    }
    return enriched, report
