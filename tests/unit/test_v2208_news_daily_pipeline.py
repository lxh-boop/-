from __future__ import annotations

import json

import pandas as pd

import news_data


def test_eastmoney_referer_url_encodes_chinese_keyword(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        text = "cb({\"result\":{\"cmsArticleWebOld\":[]}})"
        def raise_for_status(self):
            return None

    def fake_get(url, *, params, headers, timeout):
        captured["headers"] = dict(headers)
        captured["params"] = dict(params)
        return FakeResponse()

    monkeypatch.setattr(news_data, "_eastmoney_http_get", fake_get)
    rows = news_data._eastmoney_jsonp_rows("贵州茅台", page_index=1, page_size=10)
    assert rows == []
    referer = captured["headers"]["Referer"]
    assert "贵州茅台" not in referer
    assert "%E8%B4%B5%E5%B7%9E%E8%8C%85%E5%8F%B0" in referer
    referer.encode("latin-1")
    # Request query data may remain unicode; requests/curl_cffi URL-encode params.
    payload = json.loads(captured["params"]["param"] or "{}")
    assert payload["keyword"] == "贵州茅台"


def test_chinese_name_fallback_no_longer_becomes_provider_failed(monkeypatch) -> None:
    class FakeAk:
        @staticmethod
        def stock_news_em(**kwargs):
            raise RuntimeError("upstream parser failed")

    def fake_direct(keyword: str, *, canonical_code: str, start_date: str = "", end_date: str = ""):
        if keyword == "贵州茅台":
            return pd.DataFrame([{
                "关键词": canonical_code,
                "新闻标题": "贵州茅台普通财经新闻",
                "新闻内容": "摘要",
                "发布时间": "2026-08-07 13:00:00",
                "文章来源": "东方财富",
                "新闻链接": "https://example.test/a.html",
            }])
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
