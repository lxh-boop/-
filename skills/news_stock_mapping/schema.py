from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NewsStockMappingInput:
    news_id: str
    event_type: str
    evidence_text: str
    stock_candidates: list[dict[str, Any]] = field(default_factory=list)
    industry_rules: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsStockMappingOutput:
    news_id: str
    mappings: list[dict[str, Any]]
    dropped_candidates: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
