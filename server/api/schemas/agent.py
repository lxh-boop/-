from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentSessionCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    title: str = ""
    language: str = "zh"


class AgentSessionUpdateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=80)


class AgentMessageCreateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    role: Literal["user", "assistant", "system"] = "user"
    content: str = Field(min_length=1, max_length=20000)
    language: str = "zh"
    message_id: str = ""


class AgentTaskFinalizeRequest(BaseModel):
    user_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)


class AgentPendingActionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    confirmation_text: str = ""


class AgentSessionPage(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0
