from __future__ import annotations

import numpy as np
import pandas as pd

import config as feature_config
from event_rules import SPECIFIC_EVENT_RULES, classify_event_title
from news_data import load_event_cache, normalize_event_records, refresh_news_event_cache

ENABLE_NEWS_FEATURES = getattr(feature_config, "ENABLE_NEWS_FEATURES", True)
NEWS_EVENT_LOOKBACK_DAYS = getattr(feature_config, "NEWS_EVENT_LOOKBACK_DAYS", 5)


NEWS_EVENT_FEATURE_COLUMNS = [
    "recent_news_count_1d",
    "recent_news_count_3d",
    "recent_news_count_5d",
    "positive_event_count_5d",
    "negative_event_count_5d",
    "risk_event_count_5d",
    "has_earnings_positive",
    "has_earnings_negative",
    "has_shareholder_reduce",
    "has_shareholder_increase",
    "has_lawsuit",
    "has_penalty",
    "has_merger",
    "has_buyback",
    "has_contract_win",
]


def get_news_event_feature_cols() -> list[str]:
    return list(NEWS_EVENT_FEATURE_COLUMNS)


def _empty_feature_frame(base_data: pd.DataFrame) -> pd.DataFrame:
    base = base_data[["date", "code"]].drop_duplicates().copy()
    base["date"] = pd.to_datetime(base["date"])
    base["code"] = base["code"].astype(str).str.zfill(6)

    for col in NEWS_EVENT_FEATURE_COLUMNS:
        base[col] = 0

    return base


def _prepare_events(events: pd.DataFrame | None, stock_pool: dict | None = None) -> pd.DataFrame:
    events = normalize_event_records(events, stock_pool=stock_pool)

    if events.empty:
        return events

    events = events.copy()
    events["date"] = pd.to_datetime(events["date"])
    events["code"] = events["code"].astype(str).str.zfill(6)

    classified = events["title"].map(classify_event_title).apply(pd.Series)
    events = pd.concat([events, classified], axis=1)

    for col in [
        "is_positive_event",
        "is_negative_event",
        "is_risk_event",
        *SPECIFIC_EVENT_RULES.keys(),
    ]:
        if col not in events.columns:
            events[col] = 0
        events[col] = pd.to_numeric(events[col], errors="coerce").fillna(0).astype(int)

    return events


def build_news_event_features(
    base_data: pd.DataFrame,
    events: pd.DataFrame | None = None,
    stock_pool: dict | None = None,
) -> pd.DataFrame:
    feature_df = _empty_feature_frame(base_data)

    if not ENABLE_NEWS_FEATURES:
        return feature_df

    events = _prepare_events(events, stock_pool=stock_pool)

    if events.empty:
        return feature_df

    feature_df = feature_df.sort_values(["code", "date"]).reset_index(drop=True)
    result_parts = []

    max_window = max(NEWS_EVENT_LOOKBACK_DAYS, 5)

    for code, base_g in feature_df.groupby("code", sort=False):
        event_g = events[events["code"] == code].copy()
        out_g = base_g.copy()

        if event_g.empty:
            result_parts.append(out_g)
            continue

        event_g = event_g.sort_values("date").reset_index(drop=True)
        event_dates = event_g["date"]

        for idx, row in out_g.iterrows():
            current_date = row["date"]

            mask_1d = (event_dates <= current_date) & (
                event_dates >= current_date - pd.Timedelta(days=0)
            )
            mask_3d = (event_dates <= current_date) & (
                event_dates >= current_date - pd.Timedelta(days=2)
            )
            mask_5d = (event_dates <= current_date) & (
                event_dates >= current_date - pd.Timedelta(days=max_window - 1)
            )

            recent_5d = event_g.loc[mask_5d]

            out_g.at[idx, "recent_news_count_1d"] = int(mask_1d.sum())
            out_g.at[idx, "recent_news_count_3d"] = int(mask_3d.sum())
            out_g.at[idx, "recent_news_count_5d"] = int(mask_5d.sum())
            out_g.at[idx, "positive_event_count_5d"] = int(
                recent_5d["is_positive_event"].sum()
            )
            out_g.at[idx, "negative_event_count_5d"] = int(
                recent_5d["is_negative_event"].sum()
            )
            out_g.at[idx, "risk_event_count_5d"] = int(
                recent_5d["is_risk_event"].sum()
            )

            for flag in SPECIFIC_EVENT_RULES:
                out_g.at[idx, flag] = int(recent_5d[flag].max()) if not recent_5d.empty else 0

        result_parts.append(out_g)

    out = pd.concat(result_parts, ignore_index=True)

    for col in NEWS_EVENT_FEATURE_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(np.float32)

    return out


def add_news_event_features(
    feature_data: pd.DataFrame,
    stock_pool: dict | None = None,
    token: str | None = None,
    refresh_cache: bool = False,
    start_date=None,
    end_date=None,
) -> pd.DataFrame:
    data = feature_data.copy()

    if not ENABLE_NEWS_FEATURES:
        return data

    if data.empty:
        return data

    if start_date is None:
        start_date = data["date"].min()

    if end_date is None:
        end_date = data["date"].max()

    if refresh_cache:
        events, status = refresh_news_event_cache(
            token=token,
            stock_pool=stock_pool,
            start_date=start_date,
            end_date=end_date,
        )
        print(f"[News] refresh status = {status}")
    else:
        events = load_event_cache(stock_pool=stock_pool)

    event_features = build_news_event_features(
        base_data=data,
        events=events,
        stock_pool=stock_pool,
    )

    data["date"] = pd.to_datetime(data["date"])
    data["code"] = data["code"].astype(str).str.zfill(6)
    data = data.drop(columns=[c for c in NEWS_EVENT_FEATURE_COLUMNS if c in data.columns])
    data = data.merge(event_features, on=["date", "code"], how="left")

    for col in NEWS_EVENT_FEATURE_COLUMNS:
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0).astype(np.float32)

    print(
        f"[News] event features added, columns={len(NEWS_EVENT_FEATURE_COLUMNS)}, "
        f"event_rows={len(events)}"
    )

    return data
