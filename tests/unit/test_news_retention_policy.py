from __future__ import annotations

from datetime import datetime

from rag.retention_policy import classify_news_retention, is_chunk_cleanable


def test_recent_news_is_kept_hot() -> None:
    decision = classify_news_retention(
        {"publish_time": "2026-06-01 10:00:00"},
        now=datetime(2026, 6, 11),
    )
    assert decision.action == "keep"
    assert decision.retention_level == "hot"


def test_agent_used_chunk_is_not_cleanable() -> None:
    item = {
        "publish_time": "2025-01-01 10:00:00",
        "used_in_decision": 1,
    }
    decision = classify_news_retention(item, now=datetime(2026, 6, 11))
    assert decision.action == "keep"
    assert decision.keep_evidence_snapshot
    assert not is_chunk_cleanable(item, now=datetime(2026, 6, 11))


def test_old_regular_news_can_delete_body_embedding() -> None:
    item = {
        "publish_time": "2025-01-01 10:00:00",
        "used_in_decision": 0,
        "is_major_event": 0,
    }
    decision = classify_news_retention(item, now=datetime(2026, 6, 11))
    assert decision.action == "delete_body_embedding"
    assert is_chunk_cleanable(item, now=datetime(2026, 6, 11))
