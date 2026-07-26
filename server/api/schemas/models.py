from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ModelMetricData(BaseModel):
    metrics: dict[str, Any] = Field(default_factory=dict)
    selected_strategy: dict[str, Any] = Field(default_factory=dict)
