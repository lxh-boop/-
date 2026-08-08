from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

import news_data
from scheduler import daily_worker, runtime_scheduler
from scheduler.schemas import SchedulerStatus


def test_direct_eastmoney_paginates_until_requested_window(monkeypatch) -> None:
    monkeypatch.setattr(news_data, "EASTMONEY_STOCK_NEWS_MAX_PAGES", 3)
    monkeypatch.setattr(news_data, "EASTMONEY_STOCK_NEWS_PAGE_SIZE", 100)
    calls: list[int] = []

    def fake_rows(keyword: str, *, page_index: int, page_size: int):
        calls.append(page_index)
        if page_index == 1:
            return [{
                "date": "2026-08-01 10:00:00",
                "mediaName": "东方财富",
                "code": "OLD001",
                "title": "旧新闻",
                "content": "旧摘要",
            }]
        if page_index == 2:
            return [{
                "date": "2026-08-07 10:00:00",
                "mediaName": "东方财富",
                "code": "NEW001",
                "title": "目标日期新闻",
                "content": "摘要",
            }]
        return [{
            "date": "2026-07-30 10:00:00",
            "mediaName": "东方财富",
            "code": "OLDER",
            "title": "更旧新闻",
            "content": "摘要",
        }]

    monkeypatch.setattr(news_data, "_eastmoney_jsonp_rows", fake_rows)
    result = news_data._direct_eastmoney_stock_news(
        "600519",
        canonical_code="600519",
        start_date="20260806",
        end_date="20260807",
    )
    assert calls == [1, 2, 3]
    assert len(result) == 1
    assert result.iloc[0]["新闻标题"] == "目标日期新闻"


def test_stock_news_name_fallback_classified_success(monkeypatch) -> None:
    class FakeAk:
        @staticmethod
        def stock_news_em(**kwargs):
            raise RuntimeError("upstream parser failed")

    def fake_direct(keyword: str, *, canonical_code: str, start_date: str = "", end_date: str = ""):
        if keyword == "贵州茅台":
            return pd.DataFrame([
                {
                    "关键词": canonical_code,
                    "新闻标题": "贵州茅台普通财经新闻",
                    "新闻内容": "摘要",
                    "发布时间": "2026-08-07 13:00:00",
                    "文章来源": "东方财富",
                    "新闻链接": "https://example.test/a.html",
                }
            ])
        return pd.DataFrame()

    monkeypatch.setattr(news_data, "_direct_eastmoney_stock_news", fake_direct)
    frame, status = news_data._call_akshare_stock_news(
        FakeAk,
        "600519",
        stock_name="贵州茅台",
        start_date="20260806",
        end_date="20260807",
    )
    assert len(frame) == 1
    assert status["status"] == "success"
    assert status["provider"] == "eastmoney_name"


def test_scheduler_overall_partial_when_public_data_degraded(tmp_path) -> None:
    order: list[str] = []

    def market_runner(**kwargs):
        order.append("market")
        return {"status": SchedulerStatus.SUCCESS, "metadata": {"signal_date": "2026-08-07"}}

    def public_runner(**kwargs):
        order.append("public")
        return {
            "status": SchedulerStatus.PARTIAL_SUCCESS,
            "warnings": ["ordinary_news_provider_degraded"],
            "metadata": {
                "ranking_output_path": "outputs/shared/ranking_latest.csv",
                "news_event_count": 10,
                "public_data_ready": True,
                "public_data_healthy": False,
                "ordinary_news_status": "provider_failed",
            },
        }

    def user_runner(**kwargs):
        order.append(f"user:{kwargs['user_id']}")
        return {
            "status": SchedulerStatus.SUCCESS,
            "recommendation_count": 1,
            "paper_order_count": 0,
            "position_count": 0,
            "report_path": "",
        }

    result = daily_worker.run_scheduled_daily_update(
        trade_date="2026-08-07",
        user_ids=["cht"],
        force=True,
        dry_run=False,
        output_dir=tmp_path / "outputs",
        root=tmp_path,
        market_update_runner=market_runner,
        public_task_runner=public_runner,
        user_task_runner=user_runner,
    )
    assert order == ["market", "public", "user:cht"]
    assert result.overall_status == SchedulerStatus.PARTIAL_SUCCESS
    assert "ordinary_news_provider_degraded" in result.warnings


def test_runtime_catchup_checks_public_health_even_when_ranking_current(monkeypatch) -> None:
    monkeypatch.setattr(runtime_scheduler, "read_ranking_signal_date", lambda output_dir="outputs": "2026-08-07")
    monkeypatch.setattr(runtime_scheduler, "expected_signal_date", lambda now=None: "2026-08-07")
    monkeypatch.setattr(
        runtime_scheduler,
        "load_latest_job_status",
        lambda root=".": {
            "trade_date": "2026-08-07",
            "public_task_status": {
                "status": SchedulerStatus.PARTIAL_SUCCESS,
                "metadata": {
                    "public_data_ready": True,
                    "public_data_healthy": False,
                    "ordinary_news_status": "provider_failed",
                },
            },
        },
    )
    config = {"enabled": True, "catch_up": True, "hour": 20, "minute": 0}
    now = datetime(2026, 8, 7, 21, 0, tzinfo=runtime_scheduler._SHANGHAI_TZ)
    assert runtime_scheduler._should_catch_up(config, now=now) is True
