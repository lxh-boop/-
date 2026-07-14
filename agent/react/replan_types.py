from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id(prefix: str) -> str:
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


class ReplanReason(str, Enum):
    MISSING_REQUIRED_CONTEXT = "missing_required_context"
    MISSING_REQUIRED_PARAMETER = "missing_required_parameter"
    TOOL_ERROR_RECOVERABLE = "tool_error_recoverable"
    TOOL_ERROR_BLOCKING = "tool_error_blocking"
    TOOL_RESULT_EMPTY = "tool_result_empty"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    MEMORY_INSUFFICIENT = "memory_insufficient"
    PERMISSION_BLOCKED = "permission_blocked"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    USER_GOAL_CHANGED = "user_goal_changed"
    TASK_DEPENDENCY_FAILED = "task_dependency_failed"
    MAX_CONTEXT_BUDGET_EXCEEDED = "max_context_budget_exceeded"
    MAX_REPLAN_LIMIT_REACHED = "max_replan_limit_reached"

    @classmethod
    def from_value(cls, value: "ReplanReason | str | None") -> "ReplanReason":
        if isinstance(value, ReplanReason):
            return value
        text = str(value or ReplanReason.TOOL_ERROR_RECOVERABLE.value)
        try:
            return cls(text)
        except ValueError:
            return ReplanReason.TOOL_ERROR_RECOVERABLE


class ReplanScope(str, Enum):
    NO_REPLAN = "NO_REPLAN"
    CURRENT_TASK = "CURRENT_TASK"
    DEPENDENT_TASKS = "DEPENDENT_TASKS"
    PLAN_SUMMARY_ONLY = "PLAN_SUMMARY_ONLY"
    ASK_USER_CLARIFICATION = "ASK_USER_CLARIFICATION"
    BLOCK_AND_REPORT = "BLOCK_AND_REPORT"

    @classmethod
    def from_value(cls, value: "ReplanScope | str | None") -> "ReplanScope":
        if isinstance(value, ReplanScope):
            return value
        text = str(value or ReplanScope.NO_REPLAN.value)
        try:
            return cls(text)
        except ValueError:
            return ReplanScope.NO_REPLAN


class ReplanDecisionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SKIPPED = "SKIPPED"
    APPLIED = "APPLIED"
    BLOCKED = "BLOCKED"
    WAIT_APPROVAL = "WAIT_APPROVAL"

    @classmethod
    def from_value(cls, value: "ReplanDecisionStatus | str | None") -> "ReplanDecisionStatus":
        if isinstance(value, ReplanDecisionStatus):
            return value
        text = str(value or ReplanDecisionStatus.SKIPPED.value)
        try:
            return cls(text)
        except ValueError:
            return ReplanDecisionStatus.SKIPPED


@dataclass
class ReplanDecision:
    replan_decision_id: str = field(default_factory=lambda: _id("replan"))
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    trigger_observation_id: str = ""
    reason: ReplanReason = ReplanReason.TOOL_ERROR_RECOVERABLE
    scope: ReplanScope = ReplanScope.NO_REPLAN
    status: ReplanDecisionStatus = ReplanDecisionStatus.SKIPPED
    created_at: str = field(default_factory=_now_text)
    summary: str = ""
    suggested_plan_patch: dict[str, Any] = field(default_factory=dict)
    blocked_by: list[str] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.reason = ReplanReason.from_value(self.reason)
        self.scope = ReplanScope.from_value(self.scope)
        self.status = ReplanDecisionStatus.from_value(self.status)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReplanDecision":
        data = dict(value or {})
        data["reason"] = ReplanReason.from_value(data.get("reason"))
        data["scope"] = ReplanScope.from_value(data.get("scope"))
        data["status"] = ReplanDecisionStatus.from_value(data.get("status"))
        return cls(**data)
