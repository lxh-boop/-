from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _critic_id() -> str:
    return f"critic_{uuid4().hex[:12]}"


def _issue_id() -> str:
    return f"critic_issue_{uuid4().hex[:12]}"


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


class CriticAction(str, Enum):
    PASS = "PASS"
    REVISE_ANSWER = "REVISE_ANSWER"
    REPLAN_READONLY = "REPLAN_READONLY"
    ASK_USER = "ASK_USER"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK_AND_REPORT = "BLOCK_AND_REPORT"
    HANDOFF_REQUESTED = "HANDOFF_REQUESTED"

    @classmethod
    def from_value(cls, value: "CriticAction | str | None") -> "CriticAction":
        if isinstance(value, CriticAction):
            return value
        text = str(value or cls.PASS.value).upper()
        try:
            return cls(text)
        except ValueError:
            return cls.PASS


class CriticSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKING = "BLOCKING"

    @classmethod
    def from_value(cls, value: "CriticSeverity | str | None") -> "CriticSeverity":
        if isinstance(value, CriticSeverity):
            return value
        text = str(value or cls.INFO.value).upper()
        try:
            return cls(text)
        except ValueError:
            return cls.INFO


class CriticTargetType(str, Enum):
    FINAL_REPORT = "FINAL_REPORT"
    TOOL_RESULT = "TOOL_RESULT"
    PORTFOLIO_PROPOSAL = "PORTFOLIO_PROPOSAL"
    RISK_ANALYSIS = "RISK_ANALYSIS"
    REPLAN_DECISION = "REPLAN_DECISION"
    OBSERVATION_TRACE = "OBSERVATION_TRACE"
    MEMORY_SUMMARY = "MEMORY_SUMMARY"
    SYSTEM_STATUS = "SYSTEM_STATUS"

    @classmethod
    def from_value(cls, value: "CriticTargetType | str | None") -> "CriticTargetType":
        if isinstance(value, CriticTargetType):
            return value
        text = str(value or cls.FINAL_REPORT.value).upper()
        try:
            return cls(text)
        except ValueError:
            return cls.FINAL_REPORT


class CriticVerdict(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"

    @classmethod
    def from_value(cls, value: "CriticVerdict | str | None") -> "CriticVerdict":
        if isinstance(value, CriticVerdict):
            return value
        text = str(value or cls.PASS.value).upper()
        try:
            return cls(text)
        except ValueError:
            return cls.PASS


class CriticIssueCategory(str, Enum):
    TOOL_FAILURE = "TOOL_FAILURE"
    EMPTY_RESULT = "EMPTY_RESULT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    MISSING_USER_INFO = "MISSING_USER_INFO"
    WRITE_WITHOUT_APPROVAL = "WRITE_WITHOUT_APPROVAL"
    SENSITIVE_DATA_EXPOSURE = "SENSITIVE_DATA_EXPOSURE"
    RISK_POLICY_GAP = "RISK_POLICY_GAP"
    RISK_PREFERENCE_CONFLICT = "RISK_PREFERENCE_CONFLICT"
    PERMISSION_BLOCKED = "PERMISSION_BLOCKED"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    FORMAT_OR_DISCLAIMER_GAP = "FORMAT_OR_DISCLAIMER_GAP"
    HANDOFF_NEEDED = "HANDOFF_NEEDED"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_value(cls, value: "CriticIssueCategory | str | None") -> "CriticIssueCategory":
        if isinstance(value, CriticIssueCategory):
            return value
        text = str(value or cls.UNKNOWN.value).upper()
        try:
            return cls(text)
        except ValueError:
            return cls.UNKNOWN


@dataclass
class CriticIssue:
    issue_id: str = field(default_factory=_issue_id)
    category: CriticIssueCategory = CriticIssueCategory.UNKNOWN
    severity: CriticSeverity = CriticSeverity.INFO
    target_type: CriticTargetType = CriticTargetType.FINAL_REPORT
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    memory_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.category = CriticIssueCategory.from_value(self.category)
        self.severity = CriticSeverity.from_value(self.severity)
        self.target_type = CriticTargetType.from_value(self.target_type)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CriticIssue":
        data = dict(value or {})
        data["category"] = CriticIssueCategory.from_value(data.get("category"))
        data["severity"] = CriticSeverity.from_value(data.get("severity"))
        data["target_type"] = CriticTargetType.from_value(data.get("target_type"))
        return cls(**data)


@dataclass
class CriticResult:
    critic_id: str = field(default_factory=_critic_id)
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    target_type: CriticTargetType = CriticTargetType.FINAL_REPORT
    target_ref: str = ""
    target_summary: str = ""
    verdict: CriticVerdict = CriticVerdict.PASS
    action: CriticAction = CriticAction.PASS
    severity: CriticSeverity = CriticSeverity.INFO
    score: float = 1.0
    issues: list[CriticIssue] = field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    memory_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    revision_instruction: str = ""
    replan_hint: str = ""
    handoff_hint: str = ""
    requires_user_confirmation: bool = False
    created_at: str = field(default_factory=_now_text)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.target_type = CriticTargetType.from_value(self.target_type)
        self.verdict = CriticVerdict.from_value(self.verdict)
        self.action = CriticAction.from_value(self.action)
        self.severity = CriticSeverity.from_value(self.severity)
        self.issues = [
            issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(dict(issue or {}))
            for issue in (self.issues or [])
        ]
        self.score = max(0.0, min(1.0, float(self.score)))

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CriticResult":
        data = dict(value or {})
        data["target_type"] = CriticTargetType.from_value(data.get("target_type"))
        data["verdict"] = CriticVerdict.from_value(data.get("verdict"))
        data["action"] = CriticAction.from_value(data.get("action"))
        data["severity"] = CriticSeverity.from_value(data.get("severity"))
        data["issues"] = [
            item if isinstance(item, CriticIssue) else CriticIssue.from_dict(dict(item or {}))
            for item in (data.get("issues") or [])
        ]
        return cls(**data)


@dataclass
class CriticSummary:
    critic_id: str
    target_type: CriticTargetType
    action: CriticAction
    severity: CriticSeverity
    score: float = 1.0
    issue_count: int = 0
    summary: str = ""
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    blocking: bool = False

    def __post_init__(self) -> None:
        self.target_type = CriticTargetType.from_value(self.target_type)
        self.action = CriticAction.from_value(self.action)
        self.severity = CriticSeverity.from_value(self.severity)
        self.score = max(0.0, min(1.0, float(self.score)))

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
