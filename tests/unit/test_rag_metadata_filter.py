from __future__ import annotations

from rag.metadata_filter import metadata_matches
from rag.schemas import RagChunk


def test_metadata_filter_blocks_future_publish_time() -> None:
    chunk = RagChunk(
        chunk_id="chunk_001",
        news_id="news_001",
        chunk_index=0,
        chunk_text="盘后公告。",
        publish_time="2026-06-11 18:30:00",
        trade_date="2026-06-12",
        stock_codes=["300750"],
    )

    assert not metadata_matches(
        chunk,
        {
            "stock_code": "300750",
            "decision_time": "2026-06-11 14:30:00",
        },
    )


def test_metadata_filter_allows_available_news() -> None:
    chunk = RagChunk(
        chunk_id="chunk_001",
        news_id="news_001",
        chunk_index=0,
        chunk_text="盘中公告。",
        publish_time="2026-06-11 10:30:00",
        trade_date="2026-06-11",
        stock_codes=["300750"],
        event_type="公告",
        is_announcement=True,
    )

    assert metadata_matches(
        chunk,
        {
            "stock_code": "300750",
            "decision_time": "2026-06-11 14:30:00",
            "trade_date_start": "2026-06-11",
            "trade_date_end": "2026-06-11",
            "event_type": "公告",
            "is_announcement": True,
        },
    )


def test_metadata_filter_compares_aware_decision_time_with_naive_publish_time() -> None:
    chunk = RagChunk(
        chunk_id="chunk_aware_time",
        news_id="news_aware_time",
        chunk_index=0,
        chunk_text="盘中公告。",
        publish_time="2026-06-11 10:30:00",
        trade_date="2026-06-11",
        stock_codes=["300750"],
    )

    assert metadata_matches(
        chunk,
        {
            "stock_code": "300750",
            "decision_time": "2026-06-11T14:30:00+08:00",
        },
    )
