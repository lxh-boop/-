from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SignalFusionInput:
    stock_code: str
    trade_date: str
    kline_score: float
    model_confidence_score: float
    news_score: float = 0.0
    user_preference_score: float = 0.0
    risk_penalty: float = 0.0
    concentration_penalty: float = 0.0
    weights: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SignalFusionOutput:
    stock_code: str
    trade_date: str
    kline_score: float
    news_score: float
    risk_penalty: float
    final_score: float
    action: str
    target_weight: float
    reason: str
    risk_warning: str
    metadata: dict[str, Any] = field(default_factory=dict)
