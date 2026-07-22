from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
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
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _str_list(value: Any, *, limit: int = 100) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item) for item in list(value)[:limit] if str(item or "").strip()]


def _dict_list(value: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in list(value)[:limit] if isinstance(item, dict)]


def _compact_contract_value(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 4,
    max_items: int = 10,
    max_chars: int = 600,
) -> Any:
    """Bound data passed between specialists without dropping key business facts."""
    if depth >= max_depth:
        if isinstance(value, (dict, list, tuple, set)):
            return "<summarized>"
        return str(value)[:max_chars]
    if isinstance(value, str):
        return value[:max_chars] + ("…" if len(value) > max_chars else "")
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:max_items]:
            lowered = str(key).lower()
            if lowered in {
                "raw_payload", "raw_tool_payload", "tool_calls", "arguments",
                "sql", "traceback", "stack_trace", "confirmation_token",
                "confirmation_token_hash", "api_key", "password", "secret",
                "private_chain_of_thought", "chain_of_thought", "reasoning_content",
            }:
                continue
            result[str(key)] = _compact_contract_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_chars=max_chars,
            )
        return result
    if isinstance(value, (list, tuple, set)):
        rows = list(value)
        return [
            _compact_contract_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_items=max_items,
                max_chars=max_chars,
            )
            for item in rows[:max_items]
        ]
    return str(value)[:max_chars]


class TaskStatus(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_CONTEXT = "waiting_context"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def from_value(cls, value: Any) -> "TaskStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        return cls.CREATED


class ResultStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NEED_CONTEXT = "need_context"
    FAILED = "failed"
    PROPOSAL_READY = "proposal_ready"
    BLOCKED = "blocked"

    @classmethod
    def from_value(cls, value: Any) -> "ResultStatus":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        for item in cls:
            if item.value == text:
                return item
        return cls.FAILED


@dataclass(frozen=True)
class AgentCapabilityCard:
    agent_id: str
    role: str
    description: str
    accepted_task_types: list[str] = field(default_factory=list)
    input_description: str = ""
    output_types: list[str] = field(default_factory=list)
    supports_parallel: bool = True
    can_generate_proposal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def safe_for_coordinator(self) -> dict[str, Any]:
        # Capability cards intentionally contain no tool names, schemas, paths or APIs.
        return self.to_dict()


@dataclass
class MissingContextItem:
    key: str
    description: str
    expected_format: str = ""
    reason: str = ""
    searched_sources: list[str] = field(default_factory=list)
    blocking: bool = True

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.description = str(self.description or self.key or "required context").strip()
        self.expected_format = str(self.expected_format or "").strip()
        self.reason = str(self.reason or "").strip()
        self.searched_sources = _str_list(self.searched_sources, limit=20)
        self.blocking = bool(self.blocking)

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MissingContextItem":
        return cls(**dict(value or {}))


@dataclass
class MemoryUpdate:
    key: str
    value: Any
    value_type: str = "json"
    source_type: str = "agent_result"
    source_ref: str = ""
    confirmed: bool = False
    confidence: float = 0.8
    summary: str = ""

    def __post_init__(self) -> None:
        self.key = str(self.key or "").strip()
        self.value_type = str(self.value_type or "json")
        self.source_type = str(self.source_type or "agent_result")
        self.source_ref = str(self.source_ref or "")
        self.confirmed = bool(self.confirmed)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.8
        self.summary = str(self.summary or "")[:800]

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryUpdate":
        return cls(**dict(value or {}))


@dataclass
class AgentTask:
    task_id: str
    run_id: str
    session_id: str
    assigned_agent: str
    objective: str
    task_type: str
    constraints: list[str] = field(default_factory=list)
    input_refs: list[str] = field(default_factory=list)
    dependency_task_ids: list[str] = field(default_factory=list)
    expected_output_type: str = "agent_result"
    priority: int = 1
    status: TaskStatus = TaskStatus.CREATED
    attempt: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or new_id("task"))
        self.run_id = str(self.run_id or "")
        self.session_id = str(self.session_id or "")
        self.assigned_agent = str(self.assigned_agent or "").upper()
        self.objective = str(self.objective or "").strip()
        self.task_type = str(self.task_type or "general_analysis").strip()
        self.constraints = _str_list(self.constraints, limit=30)
        self.input_refs = _str_list(self.input_refs, limit=50)
        self.dependency_task_ids = _str_list(self.dependency_task_ids, limit=50)
        self.expected_output_type = str(self.expected_output_type or "agent_result")
        try:
            self.priority = max(0, min(10, int(self.priority)))
        except (TypeError, ValueError):
            self.priority = 1
        self.status = TaskStatus.from_value(self.status)
        try:
            self.attempt = max(1, int(self.attempt))
        except (TypeError, ValueError):
            self.attempt = 1
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def safe_for_coordinator(self) -> dict[str, Any]:
        # Internal task metadata may contain compatibility details such as legacy
        # tool-level tasks. Those details never enter the coordinator prompt/result.
        return {
            "task_id": self.task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "assigned_agent": self.assigned_agent,
            "objective": self.objective,
            "task_type": self.task_type,
            "constraints": list(self.constraints),
            "input_refs": list(self.input_refs),
            "dependency_task_ids": list(self.dependency_task_ids),
            "expected_output_type": self.expected_output_type,
            "priority": self.priority,
            "status": self.status.value,
            "attempt": self.attempt,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentTask":
        return cls(**dict(value or {}))


@dataclass
class AgentResult:
    task_id: str
    agent_id: str
    status: ResultStatus
    summary: str = ""
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    confidence: float = 0.0
    evidence_refs: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_items: list[MissingContextItem] = field(default_factory=list)
    memory_updates: list[MemoryUpdate] = field(default_factory=list)
    suggested_next_agents: list[str] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.task_id = str(self.task_id or "")
        self.agent_id = str(self.agent_id or "").upper()
        self.status = ResultStatus.from_value(self.status)
        self.summary = str(self.summary or "")[:5000]
        self.findings = _dict_list(self.findings, limit=50)
        self.recommendations = _str_list(self.recommendations, limit=30)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.0
        self.evidence_refs = _dict_list(self.evidence_refs, limit=100)
        self.warnings = _str_list(self.warnings, limit=30)
        self.missing_items = [
            item if isinstance(item, MissingContextItem) else MissingContextItem.from_dict(item)
            for item in list(self.missing_items or [])[:30]
            if isinstance(item, (MissingContextItem, dict))
        ]
        self.memory_updates = [
            item if isinstance(item, MemoryUpdate) else MemoryUpdate.from_dict(item)
            for item in list(self.memory_updates or [])[:50]
            if isinstance(item, (MemoryUpdate, dict))
        ]
        self.suggested_next_agents = [item.upper() for item in _str_list(self.suggested_next_agents, limit=20)]
        self.artifact_refs = _dict_list(self.artifact_refs, limit=100)
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    def standardized_for_handoff(self) -> dict[str, Any]:
        """Compact, versioned contract used for Agent-to-Agent dependencies."""
        safe_metadata = {
            key: value
            for key, value in self.metadata.items()
            if key in {
                "task_type",
                "attempt",
                "partial_reason",
                "proposal_id",
                "plan_id",
                "requires_approval",
            }
        }
        return {
            "contract_version": "standardized_agent_result.v1",
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "summary": self.summary[:1400],
            "findings": [
                _compact_contract_value(item, max_depth=4, max_items=8, max_chars=500)
                for item in self.findings[:8]
            ],
            "recommendations": list(self.recommendations[:8]),
            "confidence": self.confidence,
            "evidence_refs": [
                _compact_contract_value(item, max_depth=3, max_items=8, max_chars=300)
                for item in self.evidence_refs[:12]
            ],
            "warnings": list(self.warnings[:8]),
            "missing_items": [item.to_dict() for item in self.missing_items[:8]],
            "artifact_refs": [
                _compact_contract_value(item, max_depth=3, max_items=8, max_chars=300)
                for item in self.artifact_refs[:12]
            ],
            "metadata": _compact_contract_value(
                safe_metadata,
                max_depth=3,
                max_items=10,
                max_chars=300,
            ),
        }

    def safe_for_coordinator(self) -> dict[str, Any]:
        # The coordinator receives only standardized specialist conclusions and
        # references; raw tool payloads, tool names and hidden plans are omitted.
        safe_metadata = {
            key: value
            for key, value in self.metadata.items()
            if key in {
                "task_type",
                "attempt",
                "duration_ms",
                "internal_call_count",
                "context_access_count",
                "partial_reason",
                "proposal_id",
                "plan_id",
                "requires_approval",
            }
        }
        return {
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "status": self.status.value,
            "summary": self.summary,
            "findings": list(self.findings),
            "recommendations": list(self.recommendations),
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "warnings": list(self.warnings),
            "missing_items": [item.to_dict() for item in self.missing_items],
            "suggested_next_agents": list(self.suggested_next_agents),
            "artifact_refs": list(self.artifact_refs),
            "metadata": safe_metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentResult":
        return cls(**dict(value or {}))


@dataclass
class SessionMemoryItem:
    memory_id: str
    session_id: str
    key: str
    value: Any
    value_type: str = "json"
    summary: str = ""
    source_type: str = ""
    source_ref: str = ""
    confirmed: bool = False
    confidence: float = 0.8
    version: int = 1
    status: str = "active"
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)
    expires_at: str = ""

    def __post_init__(self) -> None:
        self.memory_id = str(self.memory_id or new_id("smem"))
        self.session_id = str(self.session_id or "")
        self.key = str(self.key or "").strip()
        self.value_type = str(self.value_type or "json")
        self.summary = str(self.summary or "")[:1200]
        self.source_type = str(self.source_type or "")
        self.source_ref = str(self.source_ref or "")
        self.confirmed = bool(self.confirmed)
        try:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))
        except (TypeError, ValueError):
            self.confidence = 0.8
        try:
            self.version = max(1, int(self.version))
        except (TypeError, ValueError):
            self.version = 1
        self.status = str(self.status or "active")
        self.created_at = str(self.created_at or now_text())
        self.updated_at = str(self.updated_at or self.created_at)
        self.expires_at = str(self.expires_at or "")

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
