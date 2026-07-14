from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class KlinePredictionInterpretationInput:
    trade_date: str
    stock_code: str
    stock_name: str
    model_name: str
    pred_score: float
    pred_rank: int | None = None
    pred_return: float | None = None
    confidence: str | None = None
    risk_score: float | None = None
    feature_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KlinePredictionInterpretationOutput:
    stock_code: str
    model_reliability: str
    reliability_score: float
    key_factors: list[str]
    uncertainty: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
