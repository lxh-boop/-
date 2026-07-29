from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class StockDetailData(BaseModel):
    stock_code: str
    name: str = ""
    ranking: dict[str, Any] = Field(default_factory=dict)
    market: dict[str, Any] = Field(default_factory=dict)
    event_count: int = 0
    found: bool = False
