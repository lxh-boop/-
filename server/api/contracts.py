from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class OperationRequest(BaseModel):
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class OperationResponse(BaseModel):
    success: bool = True
    data: Any = None
    error: dict[str, Any] | None = None
    request_id: str = ""
