from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class PublicSettingsData(BaseModel):
    universe: str = ""
    model_backend: str = ""
    model_version: str = "latest"
    default_topk: int = 10
    current_user_id: str = "default"
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    credentials: dict[str, bool] = Field(default_factory=dict)
    llm: dict[str, Any] = Field(default_factory=dict)
    scheduler: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True
