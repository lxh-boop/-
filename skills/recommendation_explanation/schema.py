from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RecommendationExplanationInput:
    user_id: str
    trade_date: str
    stock_code: str
    action: str
    final_score: float
    model_reason: str = ""
    news_reason: str = ""
    user_reason: str = ""
    evidence: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecommendationExplanationOutput:
    stock_code: str
    action: str
    explanation: str
    evidence_summary: list[str]
    risk_warning: str
    disclaimer: str
    metadata: dict[str, Any] = field(default_factory=dict)
