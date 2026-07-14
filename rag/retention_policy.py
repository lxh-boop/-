from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from rag.utils import parse_datetime


@dataclass(frozen=True)
class RetentionDecision:
    action: str
    reason: str
    keep_evidence_snapshot: bool = False
    retention_level: str = "hot"


def classify_news_retention(
    item: dict[str, Any],
    now: datetime | None = None,
    hot_days: int = 30,
    warm_days: int = 180,
) -> RetentionDecision:
    now = now or datetime.utcnow()
    created_at = parse_datetime(item.get("publish_time") or item.get("created_at")) or now
    age = now - created_at
    used = bool(item.get("is_used_by_agent") or item.get("used_in_decision"))
    major = bool(item.get("is_major_event"))

    if used:
        return RetentionDecision(
            action="keep",
            reason="agent_used_evidence",
            keep_evidence_snapshot=True,
            retention_level="archive",
        )
    if major:
        return RetentionDecision(action="archive", reason="major_event", retention_level="archive")
    if age <= timedelta(days=hot_days):
        return RetentionDecision(action="keep", reason="recent_hot_news", retention_level="hot")
    if age <= timedelta(days=warm_days):
        return RetentionDecision(action="compact", reason="warm_keep_metadata_key_chunks", retention_level="warm")
    return RetentionDecision(action="delete_body_embedding", reason="old_regular_news", retention_level="cold")


def is_chunk_cleanable(chunk: dict[str, Any], now: datetime | None = None) -> bool:
    decision = classify_news_retention(chunk, now=now)
    return decision.action in {"compact", "delete_body_embedding"} and not decision.keep_evidence_snapshot
