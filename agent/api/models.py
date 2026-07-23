from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    query: str = Field(min_length=1, max_length=20_000)
    user_id: str = Field(default="default", min_length=1, max_length=128)
    session_id: str = Field(default="", max_length=160)
    reply_language: Literal["zh", "en"] | None = None
    top_k: int = Field(default=50, ge=1, le=100)
    llm_mode: str | None = Field(default=None, max_length=80)
    decomposition_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decomposition_context")
    @classmethod
    def limit_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 80:
            raise ValueError("decomposition_context has too many keys")
        return value


class ApiEnvelope(BaseModel):
    request_id: str
    status: Literal["ok", "error"]
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    elapsed_ms: float = 0.0
