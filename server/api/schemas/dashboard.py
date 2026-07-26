from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class DashboardSummaryData(BaseModel):
    ranking: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    backtest: dict[str, Any] = Field(default_factory=dict)
    news: dict[str, Any] = Field(default_factory=dict)
    feature_flags: dict[str, bool] = Field(default_factory=dict)


class DataFreshnessItem(BaseModel):
    key: str
    label: str
    status: str
    updated_at: str | None = None
    size_bytes: int | None = None
