from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WriteRequestMeta(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=200)


class ProfileUpdateRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    profile: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class CapitalChangePreviewRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    flow_type: Literal["deposit", "withdrawal"]
    amount: float = Field(gt=0)
    effective_date: str | None = None
    reason: str = ""


class BackfillPreviewRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    start_date: str
    end_date: str = "latest"
    initial_cash: float | None = Field(default=None, gt=0)
    force: bool = True
    resume: bool = False


class ProposalCommitRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    confirmation_text: str = Field(min_length=1, max_length=100)


class ProposalRejectRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    reason: str = "user_rejected"


class CashFlowCancelRequest(WriteRequestMeta):
    user_id: str = "refactor_test"
    confirmed: bool = False
