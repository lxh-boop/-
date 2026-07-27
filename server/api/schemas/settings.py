from __future__ import annotations

from typing import Any, Literal

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
    configuration: dict[str, Any] = Field(default_factory=dict)
    scheduler: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = False


class SettingsUpdateRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)
    confirmed: bool = False
    llm_mode: Literal["api", "local"]
    api_provider: str = Field(default="openai_compatible", max_length=80)
    api_base_url: str = Field(default="", max_length=500)
    api_model: str = Field(default="", max_length=200)
    api_credential: str | None = Field(default=None, max_length=2000)
    clear_api_credential: bool = False
    local_base_url: str = Field(default="http://127.0.0.1:11434/v1", max_length=500)
    local_model: str = Field(default="stock-agent-qwen3-4b", max_length=200)
    tushare_credential: str | None = Field(default=None, max_length=500)
    clear_tushare_credential: bool = False
