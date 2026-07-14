from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _observation_id() -> str:
    return f"obs_{uuid4().hex[:12]}"


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


class ObservationType(str, Enum):
    TOOL_SUCCESS = "TOOL_SUCCESS"
    TOOL_EMPTY_RESULT = "TOOL_EMPTY_RESULT"
    TOOL_ERROR = "TOOL_ERROR"
    TOOL_PERMISSION_BLOCKED = "TOOL_PERMISSION_BLOCKED"
    CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    MEMORY_HIT = "MEMORY_HIT"
    MEMORY_EMPTY = "MEMORY_EMPTY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_DENIED = "APPROVAL_DENIED"
    TASK_PARTIAL_SUCCESS = "TASK_PARTIAL_SUCCESS"
    TASK_FAILED = "TASK_FAILED"
    REPORT_READY = "REPORT_READY"
    USER_CLARIFICATION_NEEDED = "USER_CLARIFICATION_NEEDED"
    SYSTEM_WARNING = "SYSTEM_WARNING"

    @classmethod
    def from_value(cls, value: "ObservationType | str | None") -> "ObservationType":
        if isinstance(value, ObservationType):
            return value
        text = str(value or ObservationType.SYSTEM_WARNING.value)
        try:
            return cls(text)
        except ValueError:
            upper = text.upper()
            for item in cls:
                if item.value == upper:
                    return item
            return ObservationType.SYSTEM_WARNING


class ObservationStatus(str, Enum):
    CREATED = "CREATED"
    RECORDED = "RECORDED"
    CONSUMED = "CONSUMED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"

    @classmethod
    def from_value(cls, value: "ObservationStatus | str | None") -> "ObservationStatus":
        if isinstance(value, ObservationStatus):
            return value
        text = str(value or ObservationStatus.CREATED.value)
        try:
            return cls(text)
        except ValueError:
            return ObservationStatus.CREATED


class ObservationSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"

    @classmethod
    def from_value(cls, value: "ObservationSeverity | str | None") -> "ObservationSeverity":
        if isinstance(value, ObservationSeverity):
            return value
        text = str(value or ObservationSeverity.INFO.value)
        try:
            return cls(text)
        except ValueError:
            return ObservationSeverity.INFO


class ObservationVisibility(str, Enum):
    LLM_VISIBLE = "LLM_VISIBLE"
    UI_VISIBLE = "UI_VISIBLE"
    TOOL_ONLY = "TOOL_ONLY"
    SYSTEM_ONLY = "SYSTEM_ONLY"
    AUDIT_ONLY = "AUDIT_ONLY"
    SECRET = "SECRET"

    @classmethod
    def from_value(cls, value: "ObservationVisibility | str | None") -> "ObservationVisibility":
        if isinstance(value, ObservationVisibility):
            return value
        text = str(value or ObservationVisibility.LLM_VISIBLE.value)
        try:
            return cls(text)
        except ValueError:
            return ObservationVisibility.LLM_VISIBLE


@dataclass
class ObservationEvent:
    observation_id: str = field(default_factory=_observation_id)
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    parent_task_id: str = ""
    source_message_id: str = ""
    source_tool_name: str = ""
    observation_type: ObservationType = ObservationType.SYSTEM_WARNING
    status: ObservationStatus = ObservationStatus.CREATED
    severity: ObservationSeverity = ObservationSeverity.INFO
    created_at: str = field(default_factory=_now_text)
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    memory_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    tool_call_refs: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.observation_type = ObservationType.from_value(self.observation_type)
        self.status = ObservationStatus.from_value(self.status)
        self.severity = ObservationSeverity.from_value(self.severity)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ObservationEvent":
        data = dict(value or {})
        data["observation_type"] = ObservationType.from_value(data.get("observation_type"))
        data["status"] = ObservationStatus.from_value(data.get("status"))
        data["severity"] = ObservationSeverity.from_value(data.get("severity"))
        return cls(**data)


@dataclass
class ObservationSummary:
    observation_id: str
    observation_type: ObservationType
    status: ObservationStatus
    severity: ObservationSeverity
    summary: str = ""
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_required: bool = False

    def __post_init__(self) -> None:
        self.observation_type = ObservationType.from_value(self.observation_type)
        self.status = ObservationStatus.from_value(self.status)
        self.severity = ObservationSeverity.from_value(self.severity)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
