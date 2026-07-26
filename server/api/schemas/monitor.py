from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class MonitorSummaryData(BaseModel):
    snapshot: dict[str, Any] = Field(default_factory=dict)
    alerts: list[dict[str, Any]] = Field(default_factory=list)
