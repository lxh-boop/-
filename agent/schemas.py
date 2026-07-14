from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


RISK_WARNING = "本内容仅用于机器学习、金融数据分析和项目展示，不构成投资建议。"


class AgentTaskStatus:
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    OBSERVING = "observing"
    REPLANNING = "replanning"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    REVALIDATING = "revalidating"
    COMMITTING = "committing"
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    ALL = {
        CREATED,
        PLANNING,
        RUNNING,
        OBSERVING,
        REPLANNING,
        WAITING_FOR_APPROVAL,
        REVALIDATING,
        COMMITTING,
        COMPLETED,
        PARTIALLY_COMPLETED,
        FAILED,
        CANCELLED,
        EXPIRED,
    }


class AgentStepStatus:
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    WAITING = "waiting"

    ALL = {
        PENDING,
        READY,
        RUNNING,
        SUCCEEDED,
        FAILED,
        SKIPPED,
        CANCELLED,
        WAITING,
    }


PROTECTED_BUSINESS_WRITE_TYPES = {
    "paper_order",
    "cash",
    "position",
    "cash_flow",
    "user_profile",
    "risk_preference",
    "investment_goal",
    "trading_permission",
    "business_config",
    "business_data_delete",
    "business_data_reset",
}


@dataclass
class AgentRequest:
    query: str
    model_name: Optional[str] = None
    trade_date: Optional[str] = None
    topk: int = 10


@dataclass
class ToolCallRecord:
    intent: str
    tool_name: str
    tool_args: dict[str, Any]
    success: bool
    message: str
    result_preview: str = ""


@dataclass
class SourceReference:
    source_id: str
    source_type: str
    source_title: str = ""
    source_time: str = ""
    database_record_id: str = ""
    file_path: str = ""
    content_hash: str = ""
    tool_call_id: str = ""
    retrieved_at: str = ""
    snippet: str = ""


@dataclass
class AgentRuntimeStep:
    step_id: str
    intent: str
    status: str = AgentStepStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    tool_name: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    observation_summary: str = ""
    error_type: str = ""
    retry_count: int = 0


@dataclass
class ActionProposal:
    plan_id: str
    user_id: str
    operation_type: str
    snapshot_id: str
    business_state_version: str
    plan_hash: str
    created_at: str
    expires_at: str
    before_state_summary: dict[str, Any] = field(default_factory=dict)
    proposed_changes: list[dict[str, Any]] = field(default_factory=list)
    after_state_preview: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    validation_results: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = True


def is_protected_business_write(operation_type: str) -> bool:
    return str(operation_type or "") in PROTECTED_BUSINESS_WRITE_TYPES


@dataclass
class AgentResponse:
    answer: str
    intent: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    risk_warning: str = RISK_WARNING
