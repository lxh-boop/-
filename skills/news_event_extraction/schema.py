from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NewsEventExtractionInput:
    news_id: str
    title: str
    summary: str = ""
    content: str = ""
    source: str = ""
    publish_time: str = ""
    trade_date: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsEventExtractionOutput:
    news_id: str
    event_type: str
    sentiment: str
    importance_score: float
    is_major_event: bool
    evidence_text: str
    confidence: float
    metadata: dict[str, Any] = field(default_factory=dict)
