from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

import config as data_config
from data_tushare import init_tushare_pro, ts_code_to_code

NEWS_CACHE_PATH = getattr(data_config, "NEWS_CACHE_PATH", os.path.join("data", "news_cache.csv"))
ANNOUNCEMENT_CACHE_PATH = getattr(
    data_config,
    "ANNOUNCEMENT_CACHE_PATH",
    os.path.join("data", "announcement_cache.csv"),
)


EVENT_COLUMNS = [
    "date",
    "code",
    "name",
    "title",
    "source",
    "url",
    "publish_time",
]


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def normalize_event_records(
    df: pd.DataFrame | None,
    stock_pool: dict | None = None,
    source: str = "",
) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    data = df.copy()

    title_col = _first_existing_column(
        data,
        ["title", "ann_title", "news_title", "content", "summary"],
    )
    if title_col is None:
        data["title"] = ""
    else:
        data["title"] = data[title_col].astype(str)

    if "code" not in data.columns:
        if "ts_code" in data.columns:
            data["code"] = data["ts_code"].map(ts_code_to_code)
        elif "symbol" in data.columns:
            data["code"] = data["symbol"].astype(str).str.extract(r"(\d{6})")[0]
        else:
            data["code"] = None

    data["code"] = data["code"].astype(str).str.extract(r"(\d{6})")[0]

    if stock_pool and data["code"].isna().any():
        matched_rows = []
        missing_code = data[data["code"].isna()].copy()

        for _, row in missing_code.iterrows():
            title = str(row.get("title", ""))
            for code, name in stock_pool.items():
                name = str(name or "")
                if name and name in title:
                    new_row = row.copy()
                    new_row["code"] = str(code).zfill(6)
                    new_row["name"] = name
                    matched_rows.append(new_row)

        data = data[~data["code"].isna()].copy()

        if matched_rows:
            data = pd.concat([data, pd.DataFrame(matched_rows)], ignore_index=True)

    data = data.dropna(subset=["code"]).copy()
    data["code"] = data["code"].astype(str).str.zfill(6)

    if stock_pool:
        code_set = set(stock_pool)
        data = data[data["code"].isin(code_set)].copy()
        if data.empty:
            return pd.DataFrame(columns=EVENT_COLUMNS)

    date_col = _first_existing_column(
        data,
        ["date", "ann_date", "trade_date", "publish_date", "pub_date"],
    )
    time_col = _first_existing_column(
        data,
        ["publish_time", "datetime", "pub_time", "ann_time", "time"],
    )

    if date_col is not None:
        date_raw = data[date_col].astype(str).str.slice(0, 10)
    elif time_col is not None:
        date_raw = data[time_col].astype(str).str.slice(0, 10)
    else:
        date_raw = datetime.today().strftime("%Y%m%d")

    data["date"] = pd.to_datetime(date_raw, errors="coerce")
    data = data.dropna(subset=["date"]).copy()

    if time_col is not None:
        data["publish_time"] = pd.to_datetime(data[time_col], errors="coerce")
    else:
        data["publish_time"] = data["date"]

    if "name" not in data.columns:
        data["name"] = data["code"].map(stock_pool or {}).fillna("")
    else:
        mapped_name = data["code"].map(stock_pool or {})
        data["name"] = mapped_name.fillna(data["name"]).fillna("")

    if "source" not in data.columns:
        data["source"] = source
    else:
        data["source"] = data["source"].fillna(source)

    if "url" not in data.columns and "pdf_url" in data.columns:
        data["url"] = data["pdf_url"]
    elif "url" not in data.columns:
        data["url"] = ""

    out = data[EVENT_COLUMNS].copy()
    out["title"] = out["title"].fillna("").astype(str)
    out["source"] = out["source"].fillna(source).astype(str)
    out["url"] = out["url"].fillna("").astype(str)
    out = out.drop_duplicates(subset=["date", "code", "title"], keep="last")
    out = out.sort_values(["date", "code", "publish_time"]).reset_index(drop=True)

    return out


def load_event_cache(stock_pool: dict | None = None) -> pd.DataFrame:
    frames = []

    for path, source in [
        (NEWS_CACHE_PATH, "news_cache"),
        (ANNOUNCEMENT_CACHE_PATH, "announcement_cache"),
    ]:
        if not os.path.exists(path):
            continue

        try:
            raw = pd.read_csv(path, dtype={"code": str})
            frames.append(normalize_event_records(raw, stock_pool=stock_pool, source=source))
        except Exception as e:
            print(f"[News] cache read failed, path={path}: {e}")

    if not frames:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates(subset=["date", "code", "title"], keep="last")
    data = data.sort_values(["date", "code", "publish_time"]).reset_index(drop=True)
    return data


def _merge_and_save_cache(path: str, new_df: pd.DataFrame, source: str) -> pd.DataFrame:
    old_df = pd.DataFrame(columns=EVENT_COLUMNS)

    if os.path.exists(path):
        try:
            old_df = pd.read_csv(path, dtype={"code": str})
        except Exception:
            old_df = pd.DataFrame(columns=EVENT_COLUMNS)

    data = pd.concat(
        [
            normalize_event_records(old_df, source=source),
            normalize_event_records(new_df, source=source),
        ],
        ignore_index=True,
    )
    data = data.drop_duplicates(subset=["date", "code", "title"], keep="last")
    data = data.sort_values(["date", "code", "publish_time"]).reset_index(drop=True)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    data.to_csv(path, index=False, encoding="utf-8-sig")
    return data


def fetch_tushare_announcements(
    token: str,
    stock_pool: dict | None,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    try:
        pro = init_tushare_pro(token)
        raw = pro.anns_d(
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,ann_date,title,ann_type,pdf_url",
        )
        return normalize_event_records(raw, stock_pool=stock_pool, source="tushare_anns_d")
    except Exception as e:
        print(f"[News] Tushare announcement fetch skipped: {e}")
        return pd.DataFrame(columns=EVENT_COLUMNS)


def fetch_tushare_news(
    token: str,
    stock_pool: dict | None,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    try:
        pro = init_tushare_pro(token)
        start_dt = pd.to_datetime(start_date).strftime("%Y-%m-%d 00:00:00")
        end_dt = pd.to_datetime(end_date).strftime("%Y-%m-%d 23:59:59")
        raw = pro.news(
            src="sina",
            start_date=start_dt,
            end_date=end_dt,
        )
        return normalize_event_records(raw, stock_pool=stock_pool, source="tushare_news")
    except Exception as e:
        print(f"[News] Tushare news fetch skipped: {e}")
        return pd.DataFrame(columns=EVENT_COLUMNS)


def refresh_news_event_cache(
    token: str | None,
    stock_pool: dict | None,
    start_date,
    end_date,
) -> tuple[pd.DataFrame, dict]:
    status = {
        "news_enabled": bool(token),
        "announcement_rows_fetched": 0,
        "news_rows_fetched": 0,
        "cache_rows": 0,
        "data_source_action": "cache_or_zero",
    }

    if token:
        start = pd.to_datetime(start_date).strftime("%Y%m%d")
        end = pd.to_datetime(end_date).strftime("%Y%m%d")

        ann_df = fetch_tushare_announcements(
            token=token,
            stock_pool=stock_pool,
            start_date=start,
            end_date=end,
        )
        news_df = fetch_tushare_news(
            token=token,
            stock_pool=stock_pool,
            start_date=start,
            end_date=end,
        )

        status["announcement_rows_fetched"] = int(len(ann_df))
        status["news_rows_fetched"] = int(len(news_df))

        if not ann_df.empty:
            _merge_and_save_cache(ANNOUNCEMENT_CACHE_PATH, ann_df, "tushare_anns")
            status["data_source_action"] = "fetched_or_cache"

        if not news_df.empty:
            _merge_and_save_cache(NEWS_CACHE_PATH, news_df, "tushare_news")
            status["data_source_action"] = "fetched_or_cache"

    cache = load_event_cache(stock_pool=stock_pool)
    status["cache_rows"] = int(len(cache))
    return cache, status
