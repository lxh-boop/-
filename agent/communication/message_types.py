from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _message_id(prefix: str = "msg") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _plain(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


class MessageType(str, Enum):
    USER_REQUEST = "USER_REQUEST"
    CONTEXT_CREATED = "CONTEXT_CREATED"
    GOAL_PARSED = "GOAL_PARSED"
    TASK_PLANNED = "TASK_PLANNED"
    TOOL_CALL_REQUESTED = "TOOL_CALL_REQUESTED"
    TOOL_RESULT_RECEIVED = "TOOL_RESULT_RECEIVED"
    OBSERVATION_CREATED = "OBSERVATION_CREATED"
    REPLAN_REQUESTED = "REPLAN_REQUESTED"
    REPLAN_SKIPPED = "REPLAN_SKIPPED"
    REPLAN_APPLIED = "REPLAN_APPLIED"
    REPLAN_BLOCKED = "REPLAN_BLOCKED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RESULT_RECEIVED = "APPROVAL_RESULT_RECEIVED"
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ERROR_RAISED = "ERROR_RAISED"
    WARNING_RAISED = "WARNING_RAISED"
    REPORT_DRAFTED = "REPORT_DRAFTED"
    FINAL_REPORT = "FINAL_REPORT"
    FINAL_RESPONSE = "FINAL_RESPONSE"
    HANDOFF_REQUESTED = "HANDOFF_REQUESTED"
    HANDOFF_ACCEPTED = "HANDOFF_ACCEPTED"
    HANDOFF_RESULT = "HANDOFF_RESULT"
    HANDOFF_BLOCKED = "HANDOFF_BLOCKED"
    REFLECTION_REQUESTED = "REFLECTION_REQUESTED"
    REFLECTION_RESULT = "REFLECTION_RESULT"


class MessageStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    DELIVERED = "DELIVERED"
    CONSUMED = "CONSUMED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    EXPIRED = "EXPIRED"


class MessagePriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MessageVisibility(str, Enum):
    LLM_VISIBLE = "LLM_VISIBLE"
    TOOL_ONLY = "TOOL_ONLY"
    SYSTEM_ONLY = "SYSTEM_ONLY"
    UI_VISIBLE = "UI_VISIBLE"
    AUDIT_ONLY = "AUDIT_ONLY"
    SECRET = "SECRET"


@dataclass
class AgentMessage:
    message_id: str = field(default_factory=_message_id)
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    parent_task_id: str = ""
    sender: str = ""
    receiver: str = ""
    message_type: MessageType = MessageType.USER_REQUEST
    status: MessageStatus = MessageStatus.CREATED
    priority: MessagePriority = MessagePriority.NORMAL
    created_at: str = field(default_factory=_now_text)
    payload: dict[str, Any] = field(default_factory=dict)
    payload_schema: str = ""
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    tool_call_refs: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentMessage":
        data = dict(value or {})
        for key, enum_type in {
            "message_type": MessageType,
            "status": MessageStatus,
            "priority": MessagePriority,
        }.items():
            if key in data and not isinstance(data[key], enum_type):
                data[key] = enum_type(str(data[key]))
        return cls(**data)


@dataclass
class MessageEnvelope:
    envelope_id: str = field(default_factory=lambda: _message_id("env"))
    message: AgentMessage = field(default_factory=AgentMessage)
    route: list[str] = field(default_factory=list)
    visibility: MessageVisibility = MessageVisibility.SYSTEM_ONLY
    delivery_status: MessageStatus = MessageStatus.CREATED
    retry_count: int = 0
    created_at: str = field(default_factory=_now_text)
    delivered_at: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)


@dataclass
class MessageSummary:
    message_id: str
    message_type: MessageType
    sender: str = ""
    receiver: str = ""
    summary: str = ""
    refs: dict[str, Any] = field(default_factory=dict)
    original_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
