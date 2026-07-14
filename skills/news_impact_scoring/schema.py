from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class NewsImpactScoringInput:
    news_id: str
    stock_code: str
    event_type: str
    sentiment: str
    impact_direction: str
    impact_strength: float
    impact_confidence: float
    mapping_confidence: float
    evidence_text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsImpactScoringOutput:
    news_id: str
    stock_code: str
    news_score: float
    impact_direction: str
    risk_warning: str
    confidence: float
    reason: str
    evidence_text: str
    metadata: dict[str, Any] = field(default_factory=dict)
