from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserProfileAdaptationInput:
    user_id: str
    risk_level: str
    investment_horizon: str
    liquidity_need: str
    asset_risk_level: str
    stock_code: str
    industry: str = ""
    current_positions: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserProfileAdaptationOutput:
    user_id: str
    stock_code: str
    is_suitable: bool
    suitability_level: str
    user_preference_score: float
    action: str
    reason: str
    triggered_rules: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
