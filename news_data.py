from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
ENABLE_AKSHARE_NEWS_FALLBACK = getattr(data_config, "ENABLE_AKSHARE_NEWS_FALLBACK", True)
AKSHARE_FETCH_ANNOUNCEMENTS = getattr(data_config, "AKSHARE_FETCH_ANNOUNCEMENTS", True)
AKSHARE_FETCH_STOCK_NEWS = getattr(data_config, "AKSHARE_FETCH_STOCK_NEWS", True)
AKSHARE_NOTICE_RECENT_PAGES = int(getattr(data_config, "AKSHARE_NOTICE_RECENT_PAGES", 20))
AKSHARE_NOTICE_MAX_DAYS = int(getattr(data_config, "AKSHARE_NOTICE_MAX_DAYS", 10))
AKSHARE_STOCK_NEWS_MAX_CODES = int(getattr(data_config, "AKSHARE_STOCK_NEWS_MAX_CODES", 300))
AKSHARE_REQUEST_SLEEP_SECONDS = float(getattr(data_config, "AKSHARE_REQUEST_SLEEP_SECONDS", 0.05))
AKSHARE_FETCH_WORKERS = int(getattr(data_config, "AKSHARE_FETCH_WORKERS", 4))


EVENT_COLUMNS = [
    "date",
    "code",
    "name",
    "title",
    "summary",
    "content",
    "source",
    "url",
    "publish_time",
]


def _first_existing_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _date_in_range(data: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    if data.empty or "date" not in data.columns:
        return data
    start = pd.to_datetime(start_date, errors="coerce")
    end = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start) or pd.isna(end):
        return data
    out = data.copy()
    dates = pd.to_datetime(out["date"], errors="coerce")
    out = out[(dates >= start) & (dates <= end)].copy()
    return out.reset_index(drop=True)


def _import_akshare():
    try:
        import akshare as ak  # type: ignore

        return ak
    except Exception as e:
        print(f"[News] AkShare unavailable, skipped: {e}")
        return None


def _resolve_akshare_fetch_workers(task_count: int) -> int:
    if task_count <= 0:
        return 1

    worker_value = os.environ.get("AKSHARE_FETCH_WORKERS") or os.environ.get("NEWS_FETCH_WORKERS")
    workers = AKSHARE_FETCH_WORKERS
    if worker_value:
        try:
            workers = int(float(worker_value))
        except ValueError:
            workers = AKSHARE_FETCH_WORKERS

    return max(1, min(int(workers), task_count))


def _sleep_after_akshare_request() -> None:
    if AKSHARE_REQUEST_SLEEP_SECONDS > 0:
        time.sleep(AKSHARE_REQUEST_SLEEP_SECONDS)


def _fetch_akshare_announcement_dates(ak, start_dt, end_dt) -> pd.DataFrame:
    date_values = list(pd.date_range(start=start_dt, end=end_dt, freq="D"))
    worker_count = _resolve_akshare_fetch_workers(len(date_values))
    frames_by_index: dict[int, pd.DataFrame] = {}

    def fetch_one(index: int, dt) -> tuple[int, pd.DataFrame | None, str | None]:
        date_text = dt.strftime("%Y%m%d")
        try:
            daily = ak.stock_notice_report(symbol="\u5168\u90e8", date=date_text)
            return index, daily, None
        except Exception as e:
            return index, None, f"[News] AkShare announcement date skipped for {date_text}: {e}"
        finally:
            _sleep_after_akshare_request()

    if worker_count <= 1:
        rows = [fetch_one(index, dt) for index, dt in enumerate(date_values)]
    else:
        rows = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(fetch_one, index, dt): index
                for index, dt in enumerate(date_values)
            }
            for future in as_completed(future_map):
                rows.append(future.result())

    for index, daily, error in rows:
        if error:
            print(error)
            continue
        if daily is not None and not daily.empty:
            frames_by_index[index] = daily

    frames = [frames_by_index[index] for index in range(len(date_values)) if index in frames_by_index]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _fetch_akshare_stock_news_frames(
    ak,
    stock_pool: dict,
    codes: list[str],
) -> list[pd.DataFrame]:
    worker_count = _resolve_akshare_fetch_workers(len(codes))

    def fetch_one(index: int, code: str) -> tuple[int, pd.DataFrame | None, str | None]:
        normalized_code = str(code).zfill(6)
        try:
            raw = _call_akshare_stock_news(ak, normalized_code)
            if raw is None or raw.empty:
                return index, None, None
            data = raw.copy()
            data["code"] = normalized_code
            data["name"] = stock_pool.get(normalized_code, "")
            return index, data, None
        except Exception as e:
            return index, None, f"[News] AkShare stock news skipped for {normalized_code}: {e}"
        finally:
            _sleep_after_akshare_request()

    if worker_count <= 1:
        rows = [fetch_one(index, code) for index, code in enumerate(codes)]
    else:
        rows = []
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(fetch_one, index, code): index
                for index, code in enumerate(codes)
            }
            for future in as_completed(future_map):
                rows.append(future.result())

    frames_by_index: dict[int, pd.DataFrame] = {}
    errors = 0
    for index, data, error in rows:
        if error:
            errors += 1
            if errors <= 5:
                print(error)
            continue
        if data is not None and not data.empty:
            frames_by_index[index] = data

    return [frames_by_index[index] for index in range(len(codes)) if index in frames_by_index]


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
        ["title", "ann_title", "news_title", "公告标题", "新闻标题", "标题", "content", "summary"],
    )
    if title_col is None:
        data["title"] = ""
    else:
        data["title"] = data[title_col].astype(str)

    summary_col = _first_existing_column(
        data,
        ["summary", "abstract", "brief", "digest", "description", "新闻摘要", "摘要"],
    )
    content_col = _first_existing_column(
        data,
        ["content", "body", "text", "article", "正文", "新闻内容", "公告内容"],
    )
    data["summary"] = data[summary_col].astype(str) if summary_col else ""
    data["content"] = data[content_col].astype(str) if content_col else ""

    if "code" not in data.columns:
        if "ts_code" in data.columns:
            data["code"] = data["ts_code"].map(ts_code_to_code)
        elif "symbol" in data.columns:
            data["code"] = data["symbol"].astype(str).str.extract(r"(\d{6})")[0]
        else:
            code_col = _first_existing_column(data, ["代码", "股票代码", "证券代码"])
            if code_col is not None:
                data["code"] = data[code_col].astype(str).str.extract(r"(\d{6})")[0]
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
        ["date", "ann_date", "trade_date", "publish_date", "pub_date", "公告日期", "发布日期", "新闻日期"],
    )
    time_col = _first_existing_column(
        data,
        [
            "publish_time",
            "datetime",
            "pub_time",
            "ann_time",
            "public_time",
            "time",
            "发布时间",
            "公告时间",
            "新闻时间",
        ],
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

    name_col = _first_existing_column(data, ["name", "名称", "股票简称", "证券简称"])
    if name_col is None:
        data["name"] = data["code"].map(stock_pool or {}).fillna("")
    else:
        mapped_name = data["code"].map(stock_pool or {})
        data["name"] = mapped_name.fillna(data[name_col]).fillna("")

    source_col = _first_existing_column(data, ["source", "src", "文章来源", "来源"])
    if source_col is None:
        data["source"] = source
    else:
        data["source"] = data[source_col].fillna(source)

    if "url" not in data.columns and "pdf_url" in data.columns:
        data["url"] = data["pdf_url"]
    elif "url" not in data.columns:
        url_col = _first_existing_column(data, ["新闻链接", "公告链接", "链接"])
        if url_col is not None:
            data["url"] = data[url_col]
        else:
            data["url"] = ""

    out = data[EVENT_COLUMNS].copy()
    out["title"] = out["title"].fillna("").astype(str)
    out["summary"] = out["summary"].fillna("").astype(str)
    out["content"] = out["content"].fillna("").astype(str)
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


def fetch_akshare_announcements(
    stock_pool: dict | None,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if not AKSHARE_FETCH_ANNOUNCEMENTS:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    ak = _import_akshare()
    if ak is None:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    try:
        try:
            raw = ak.stock_notice_report(
                report_type="全部",
                recent_page=str(max(1, AKSHARE_NOTICE_RECENT_PAGES)),
            )
        except TypeError:
            start_dt = pd.to_datetime(start_date, errors="coerce")
            end_dt = pd.to_datetime(end_date, errors="coerce")
            if pd.isna(start_dt) or pd.isna(end_dt):
                return pd.DataFrame(columns=EVENT_COLUMNS)
            start_dt = max(start_dt, end_dt - pd.Timedelta(days=max(1, AKSHARE_NOTICE_MAX_DAYS) - 1))
            raw = _fetch_akshare_announcement_dates(ak, start_dt, end_dt)
            data = normalize_event_records(
                raw,
                stock_pool=stock_pool,
                source="akshare_stock_notice_report",
            )
            return _date_in_range(data, start_date=start_date, end_date=end_date)
        data = normalize_event_records(
            raw,
            stock_pool=stock_pool,
            source="akshare_stock_notice_report",
        )
        return _date_in_range(data, start_date=start_date, end_date=end_date)
    except Exception as e:
        print(f"[News] AkShare announcement fetch skipped: {e}")
        return pd.DataFrame(columns=EVENT_COLUMNS)


def _call_akshare_stock_news(ak, code: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for kwargs in [{"stock": code}, {"symbol": code}]:
        try:
            return ak.stock_news_em(**kwargs)
        except TypeError as e:
            last_error = e
        except Exception:
            raise
    try:
        return ak.stock_news_em(code)
    except Exception as e:
        if last_error:
            raise last_error
        raise e


def fetch_akshare_stock_news(
    stock_pool: dict | None,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if not AKSHARE_FETCH_STOCK_NEWS:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    if not stock_pool:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    ak = _import_akshare()
    if ak is None:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    codes = list(stock_pool.keys())[: max(1, AKSHARE_STOCK_NEWS_MAX_CODES)]
    frames = _fetch_akshare_stock_news_frames(ak, stock_pool, codes)

    if not frames:
        return pd.DataFrame(columns=EVENT_COLUMNS)

    data = pd.concat(frames, ignore_index=True)
    data = normalize_event_records(
        data,
        stock_pool=stock_pool,
        source="akshare_stock_news_em",
    )
    return _date_in_range(data, start_date=start_date, end_date=end_date)


def refresh_news_event_cache(
    token: str | None,
    stock_pool: dict | None,
    start_date,
    end_date,
) -> tuple[pd.DataFrame, dict]:
    status = {
        "news_enabled": bool(token) or bool(ENABLE_AKSHARE_NEWS_FALLBACK),
        "announcement_rows_fetched": 0,
        "news_rows_fetched": 0,
        "akshare_enabled": bool(ENABLE_AKSHARE_NEWS_FALLBACK),
        "akshare_announcement_rows_fetched": 0,
        "akshare_news_rows_fetched": 0,
        "cache_rows": 0,
        "data_source_action": "cache_or_zero",
    }

    ann_df = pd.DataFrame(columns=EVENT_COLUMNS)
    news_df = pd.DataFrame(columns=EVENT_COLUMNS)
    start = pd.to_datetime(start_date).strftime("%Y%m%d")
    end = pd.to_datetime(end_date).strftime("%Y%m%d")

    if token:
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

    if ENABLE_AKSHARE_NEWS_FALLBACK:
        if ann_df.empty:
            ak_ann_df = fetch_akshare_announcements(
                stock_pool=stock_pool,
                start_date=start,
                end_date=end,
            )
            status["akshare_announcement_rows_fetched"] = int(len(ak_ann_df))
            if not ak_ann_df.empty:
                ann_df = ak_ann_df

        if news_df.empty:
            ak_news_df = fetch_akshare_stock_news(
                stock_pool=stock_pool,
                start_date=start,
                end_date=end,
            )
            status["akshare_news_rows_fetched"] = int(len(ak_news_df))
            if not ak_news_df.empty:
                news_df = ak_news_df

    if not ann_df.empty:
        _merge_and_save_cache(ANNOUNCEMENT_CACHE_PATH, ann_df, "announcement_cache")
        status["data_source_action"] = "fetched_or_cache"

    if not news_df.empty:
        _merge_and_save_cache(NEWS_CACHE_PATH, news_df, "news_cache")
        status["data_source_action"] = "fetched_or_cache"

    cache = load_event_cache(stock_pool=stock_pool)
    status["cache_rows"] = int(len(cache))
    return cache, status
