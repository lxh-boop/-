from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _handoff_id(prefix: str = "handoff") -> str:
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


class AgentRole(str, Enum):
    COORDINATOR = "COORDINATOR"
    PORTFOLIO_ANALYST = "PORTFOLIO_ANALYST"
    RISK_ANALYST = "RISK_ANALYST"
    EVIDENCE_RETRIEVER = "EVIDENCE_RETRIEVER"
    STRATEGY_GUARD = "STRATEGY_GUARD"
    REPORT_WRITER = "REPORT_WRITER"
    SYSTEM_DIAGNOSTIC = "SYSTEM_DIAGNOSTIC"

    @classmethod
    def from_value(cls, value: Any) -> "AgentRole":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip()
        if not text:
            return cls.COORDINATOR
        upper = text.upper()
        aliases = {
            "SUPERVISOR": cls.COORDINATOR,
            "MARKET_INTELLIGENCE": cls.EVIDENCE_RETRIEVER,
            "PORTFOLIO_ANALYSIS": cls.PORTFOLIO_ANALYST,
            "RISK_OPERATION": cls.STRATEGY_GUARD,
            "REPORTING": cls.REPORT_WRITER,
        }
        if upper in aliases:
            return aliases[upper]
        return cls.__members__.get(upper, cls.COORDINATOR)


class HandoffPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @classmethod
    def from_value(cls, value: Any) -> "HandoffPriority":
        if isinstance(value, cls):
            return value
        upper = str(value or "").strip().upper()
        return cls.__members__.get(upper, cls.NORMAL)


class HandoffStatus(str, Enum):
    CREATED = "CREATED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"

    @classmethod
    def from_value(cls, value: Any) -> "HandoffStatus":
        if isinstance(value, cls):
            return value
        upper = str(value or "").strip().upper()
        return cls.__members__.get(upper, cls.CREATED)


@dataclass
class HandoffRequest:
    handoff_id: str = field(default_factory=_handoff_id)
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    source_role: AgentRole = AgentRole.COORDINATOR
    target_role: AgentRole = AgentRole.PORTFOLIO_ANALYST
    reason: str = ""
    priority: HandoffPriority = HandoffPriority.NORMAL
    input_summary: dict[str, Any] = field(default_factory=dict)
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    replan_refs: list[dict[str, Any]] = field(default_factory=list)
    critic_refs: list[dict[str, Any]] = field(default_factory=list)
    memory_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    requires_approval: bool = False
    created_at: str = field(default_factory=_now_text)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.handoff_id = str(self.handoff_id or _handoff_id())
        self.conversation_id = str(self.conversation_id or "")
        self.run_id = str(self.run_id or "")
        self.task_id = str(self.task_id or "")
        self.source_role = AgentRole.from_value(self.source_role)
        self.target_role = AgentRole.from_value(self.target_role)
        self.priority = HandoffPriority.from_value(self.priority)
        self.reason = str(self.reason or "")
        self.input_summary = dict(self.input_summary or {})
        self.context_refs = _ref_list(self.context_refs)
        self.message_refs = _ref_list(self.message_refs)
        self.observation_refs = _ref_list(self.observation_refs)
        self.replan_refs = _ref_list(self.replan_refs)
        self.critic_refs = _ref_list(self.critic_refs)
        self.memory_refs = _ref_list(self.memory_refs)
        self.artifact_refs = _ref_list(self.artifact_refs)
        self.approval_refs = _ref_list(self.approval_refs)
        self.allowed_tools = _str_list(self.allowed_tools)
        self.blocked_tools = _str_list(self.blocked_tools)
        self.requires_approval = bool(self.requires_approval)
        self.created_at = str(self.created_at or _now_text())
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "HandoffRequest":
        return cls(**dict(value or {}))


@dataclass
class HandoffResult:
    handoff_id: str = ""
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    target_role: AgentRole = AgentRole.PORTFOLIO_ANALYST
    status: HandoffStatus = HandoffStatus.CREATED
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommended_action: dict[str, Any] = field(default_factory=dict)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    observation_refs: list[dict[str, Any]] = field(default_factory=list)
    critic_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_text)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.handoff_id = str(self.handoff_id or _handoff_id())
        self.conversation_id = str(self.conversation_id or "")
        self.run_id = str(self.run_id or "")
        self.task_id = str(self.task_id or "")
        self.target_role = AgentRole.from_value(self.target_role)
        self.status = HandoffStatus.from_value(self.status)
        self.summary = str(self.summary or "")
        self.findings = _ref_list(self.findings)
        self.recommended_action = dict(self.recommended_action or {})
        self.artifact_refs = _ref_list(self.artifact_refs)
        self.message_refs = _ref_list(self.message_refs)
        self.observation_refs = _ref_list(self.observation_refs)
        self.critic_refs = _ref_list(self.critic_refs)
        self.approval_refs = _ref_list(self.approval_refs)
        self.errors = _str_list(self.errors)
        self.warnings = _str_list(self.warnings)
        self.created_at = str(self.created_at or _now_text())
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "HandoffResult":
        return cls(**dict(value or {}))


@dataclass
class HandoffTrace:
    trace_id: str = field(default_factory=lambda: _handoff_id("handoff_trace"))
    run_id: str = ""
    handoff_ids: list[str] = field(default_factory=list)
    role_edges: list[dict[str, Any]] = field(default_factory=list)
    tool_edges: list[dict[str, Any]] = field(default_factory=list)
    artifact_edges: list[dict[str, Any]] = field(default_factory=list)
    critic_edges: list[dict[str, Any]] = field(default_factory=list)
    approval_edges: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.trace_id = str(self.trace_id or _handoff_id("handoff_trace"))
        self.run_id = str(self.run_id or "")
        self.handoff_ids = _str_list(self.handoff_ids)
        self.role_edges = _ref_list(self.role_edges)
        self.tool_edges = _ref_list(self.tool_edges)
        self.artifact_edges = _ref_list(self.artifact_edges)
        self.critic_edges = _ref_list(self.critic_edges)
        self.approval_edges = _ref_list(self.approval_edges)
        self.errors = _str_list(self.errors)
        self.warnings = _str_list(self.warnings)

    def add_request(self, request: HandoffRequest | dict[str, Any]) -> None:
        item = request if isinstance(request, HandoffRequest) else HandoffRequest.from_dict(dict(request or {}))
        self.handoff_ids.append(item.handoff_id)
        self.role_edges.append(
            {
                "handoff_id": item.handoff_id,
                "source_role": item.source_role.value,
                "target_role": item.target_role.value,
                "reason": item.reason[:240],
            }
        )
        for tool_name in item.allowed_tools:
            self.tool_edges.append(
                {
                    "handoff_id": item.handoff_id,
                    "target_role": item.target_role.value,
                    "tool_name": tool_name,
                }
            )
        for ref in item.artifact_refs:
            self.artifact_edges.append({"handoff_id": item.handoff_id, **dict(ref)})
        for ref in item.critic_refs:
            self.critic_edges.append({"handoff_id": item.handoff_id, **dict(ref)})
        for ref in item.approval_refs:
            self.approval_edges.append({"handoff_id": item.handoff_id, **dict(ref)})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "HandoffTrace":
        return cls(**dict(value or {}))


def _ref_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]
