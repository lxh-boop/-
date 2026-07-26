from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BacktestData(BaseModel):
    backtest_id: str = "latest"
    available: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    equity: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    predictions: list[dict[str, Any]] = Field(default_factory=list)
