from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class WebPageData(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class WebReadMeta(BaseModel):
    read_only: bool = True
    source: str = "application-service"
