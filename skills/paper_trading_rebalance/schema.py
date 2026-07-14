from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PaperTradingRebalanceInput:
    user_id: str
    trade_date: str
    cash: float
    positions: list[dict[str, Any]] = field(default_factory=list)
    fused_signals: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperTradingRebalanceOutput:
    user_id: str
    trade_date: str
    target_weights: list[dict[str, Any]]
    paper_orders: list[dict[str, Any]]
    risk_summary: dict[str, Any]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)
