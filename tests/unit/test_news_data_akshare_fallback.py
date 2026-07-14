from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pandas as pd

import news_data


COL_CODE = "\u4ee3\u7801"
COL_NAME = "\u540d\u79f0"
COL_NOTICE_TITLE = "\u516c\u544a\u6807\u9898"
COL_NOTICE_DATE = "\u516c\u544a\u65e5\u671f"
COL_NOTICE_URL = "\u516c\u544a\u94fe\u63a5"
COL_NEWS_TITLE = "\u65b0\u95fb\u6807\u9898"
COL_PUBLISH_TIME = "\u53d1\u5e03\u65f6\u95f4"
COL_SOURCE = "\u6587\u7ae0\u6765\u6e90"
COL_NEWS_URL = "\u65b0\u95fb\u94fe\u63a5"
STOCK_NAME = "\u5e73\u5b89\u94f6\u884c"
EASTMONEY = "\u4e1c\u65b9\u8d22\u5bcc"


def test_normalize_event_records_supports_akshare_chinese_columns() -> None:
    raw = pd.DataFrame(
        [
            {
                COL_CODE: "000001",
                COL_NAME: STOCK_NAME,
                COL_NOTICE_TITLE: f"{STOCK_NAME}\u516c\u544a",
                COL_NOTICE_DATE: "2026-06-17",
                COL_NOTICE_URL: "https://example.test/a",
            }
        ]
    )

    out = news_data.normalize_event_records(raw, stock_pool={"000001": STOCK_NAME}, source="akshare")

    assert len(out) == 1
    assert out.iloc[0]["code"] == "000001"
    assert out.iloc[0]["name"] == STOCK_NAME
    assert out.iloc[0]["title"] == f"{STOCK_NAME}\u516c\u544a"
    assert out.iloc[0]["source"] == "akshare"


def test_normalize_event_records_preserves_summary_and_content() -> None:
    raw = pd.DataFrame(
        [
            {
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Title text",
                "summary": "Summary text",
                "content": "Full content text",
                "source": "unit_test_news",
                "publish_time": "2026-06-17 10:00:00",
                "url": "https://example.test/n",
            }
        ]
    )

    out = news_data.normalize_event_records(raw, stock_pool={"000001": "Ping An Bank"})

    assert out.iloc[0]["title"] == "Title text"
    assert out.iloc[0]["summary"] == "Summary text"
    assert out.iloc[0]["content"] == "Full content text"


def test_refresh_news_event_cache_uses_akshare_fallback(monkeypatch, tmp_path) -> None:
    class FakeAkShare:
        @staticmethod
        def stock_notice_report(symbol: str = "all", date: str = "20260617") -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        COL_CODE: "000001",
                        COL_NAME: STOCK_NAME,
                        COL_NOTICE_TITLE: f"{STOCK_NAME}\u516c\u544a",
                        COL_NOTICE_DATE: "2026-06-17",
                        COL_NOTICE_URL: "https://example.test/a",
                    }
                ]
            )

        @staticmethod
        def stock_news_em(stock: str = "") -> pd.DataFrame:
            return pd.DataFrame(
                [
                    {
                        COL_NEWS_TITLE: f"{STOCK_NAME}\u65b0\u95fb",
                        COL_PUBLISH_TIME: "2026-06-17 10:00:00",
                        COL_SOURCE: EASTMONEY,
                        COL_NEWS_URL: "https://example.test/n",
                    }
                ]
            )

    monkeypatch.setitem(sys.modules, "akshare", FakeAkShare)
    monkeypatch.setattr(news_data, "NEWS_CACHE_PATH", str(tmp_path / "news_cache.csv"))
    monkeypatch.setattr(news_data, "ANNOUNCEMENT_CACHE_PATH", str(tmp_path / "announcement_cache.csv"))
    monkeypatch.setattr(news_data, "ENABLE_AKSHARE_NEWS_FALLBACK", True)
    monkeypatch.setattr(news_data, "AKSHARE_FETCH_ANNOUNCEMENTS", True)
    monkeypatch.setattr(news_data, "AKSHARE_FETCH_STOCK_NEWS", True)
    monkeypatch.setattr(news_data, "AKSHARE_STOCK_NEWS_MAX_CODES", 1)
    monkeypatch.setattr(news_data, "AKSHARE_REQUEST_SLEEP_SECONDS", 0.0)

    events, status = news_data.refresh_news_event_cache(
        token=None,
        stock_pool={"000001": STOCK_NAME},
        start_date="2026-06-17",
        end_date="2026-06-17",
    )

    assert status["akshare_announcement_rows_fetched"] == 1
    assert status["akshare_news_rows_fetched"] == 1
    assert status["cache_rows"] == 2
    assert len(events) == 2
    assert set(events["source"]) == {"akshare_stock_notice_report", EASTMONEY}


def test_fetch_akshare_stock_news_runs_codes_in_parallel(monkeypatch) -> None:
    state = SimpleNamespace(active=0, max_active=0, lock=threading.Lock())

    class FakeAkShare:
        @staticmethod
        def stock_news_em(stock: str = "") -> pd.DataFrame:
            with state.lock:
                state.active += 1
                state.max_active = max(state.max_active, state.active)
            try:
                time.sleep(0.05)
                return pd.DataFrame(
                    [
                        {
                            COL_NEWS_TITLE: f"{stock}\u65b0\u95fb",
                            COL_PUBLISH_TIME: "2026-06-17 10:00:00",
                            COL_SOURCE: EASTMONEY,
                            COL_NEWS_URL: f"https://example.test/{stock}",
                        }
                    ]
                )
            finally:
                with state.lock:
                    state.active -= 1

    monkeypatch.setitem(sys.modules, "akshare", FakeAkShare)
    monkeypatch.setattr(news_data, "AKSHARE_FETCH_STOCK_NEWS", True)
    monkeypatch.setattr(news_data, "AKSHARE_STOCK_NEWS_MAX_CODES", 4)
    monkeypatch.setattr(news_data, "AKSHARE_FETCH_WORKERS", 4)
    monkeypatch.setattr(news_data, "AKSHARE_REQUEST_SLEEP_SECONDS", 0.0)

    result = news_data.fetch_akshare_stock_news(
        stock_pool={
            "000001": STOCK_NAME,
            "000002": "Demo2",
            "000003": "Demo3",
            "000004": "Demo4",
        },
        start_date="20260617",
        end_date="20260617",
    )

    assert state.max_active > 1
    assert len(result) == 4
