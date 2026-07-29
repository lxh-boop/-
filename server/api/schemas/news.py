from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class NewsEventData(BaseModel):
    event_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
