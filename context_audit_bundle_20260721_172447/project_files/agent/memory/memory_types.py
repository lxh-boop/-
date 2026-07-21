from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _memory_id() -> str:
    return f"mem_{uuid4().hex[:12]}"


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


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


class MemoryType(str, Enum):
    # Legacy database compatibility only. Runtime working state is ContextBundle.
    WORKING = "WORKING"
    EPISODIC = "EPISODIC"
    SEMANTIC = "SEMANTIC"
    EVIDENCE = "EVIDENCE"
    PORTFOLIO = "PORTFOLIO"
    REFLECTION = "REFLECTION"
    PERCEPTUAL = "PERCEPTUAL"

    @classmethod
    def from_value(cls, value: Any) -> "MemoryType":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip()
        if not text:
            return cls.EPISODIC
        upper = text.upper()
        if upper in cls.__members__:
            return cls[upper]
        lowered = text.lower()
        if lowered in {
            "agent_run",
            "conversation_summary",
            "decision",
            "outcome",
            "summary",
        }:
            return cls.EPISODIC
        if lowered in {
            "feedback",
            "investment_goal",
            "language_preference",
            "long_term_preference",
            "preference",
            "profile",
            "risk_preference",
            "stable_constraint",
        }:
            return cls.SEMANTIC
        if "evidence" in lowered or "rag" in lowered or "news" in lowered:
            return cls.EVIDENCE
        if "portfolio" in lowered or "position" in lowered or "holding" in lowered:
            return cls.PORTFOLIO
        if "reflection" in lowered:
            return cls.REFLECTION
        if "percept" in lowered:
            return cls.PERCEPTUAL
        return cls.SEMANTIC


class MemoryScope(str, Enum):
    RUN = "RUN"
    CONVERSATION = "CONVERSATION"
    USER = "USER"
    PROJECT = "PROJECT"
    SYSTEM = "SYSTEM"

    @classmethod
    def from_value(cls, value: Any) -> "MemoryScope":
        if isinstance(value, cls):
            return value
        upper = str(value or "").strip().upper()
        return cls.__members__.get(upper, cls.CONVERSATION)


class MemoryVisibility(str, Enum):
    LLM_VISIBLE = "LLM_VISIBLE"
    TOOL_ONLY = "TOOL_ONLY"
    SYSTEM_ONLY = "SYSTEM_ONLY"
    UI_VISIBLE = "UI_VISIBLE"
    AUDIT_ONLY = "AUDIT_ONLY"
    SECRET = "SECRET"

    @classmethod
    def from_value(cls, value: Any) -> "MemoryVisibility":
        if isinstance(value, cls):
            return value
        upper = str(value or "").strip().upper()
        return cls.__members__.get(upper, cls.LLM_VISIBLE)


class MemoryStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"

    @classmethod
    def from_value(cls, value: Any) -> "MemoryStatus":
        if isinstance(value, cls):
            return value
        upper = str(value or "").strip().upper()
        return cls.__members__.get(upper, cls.ACTIVE)


@dataclass
class MemoryRecord:
    memory_id: str = field(default_factory=_memory_id)
    user_id: str = "default_user"
    conversation_id: str = ""
    run_id: str = ""
    task_id: str = ""
    source_type: str = ""
    source_id: str = ""
    memory_type: MemoryType = MemoryType.EPISODIC
    memory_subtype: str = ""
    scope: MemoryScope = MemoryScope.CONVERSATION
    visibility: MemoryVisibility = MemoryVisibility.LLM_VISIBLE
    status: MemoryStatus = MemoryStatus.ACTIVE
    content: str = ""
    summary: str = ""
    topics: list[str] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.8
    created_at: str = field(default_factory=_now_text)
    updated_at: str = field(default_factory=_now_text)
    valid_from: str = ""
    valid_until: str = ""
    supersedes_memory_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    context_refs: list[dict[str, Any]] = field(default_factory=list)
    message_refs: list[dict[str, Any]] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.memory_type = MemoryType.from_value(self.memory_type)
        self.scope = MemoryScope.from_value(self.scope)
        self.visibility = MemoryVisibility.from_value(self.visibility)
        self.status = MemoryStatus.from_value(self.status)
        self.memory_id = str(self.memory_id or _memory_id())
        self.user_id = str(self.user_id or "default_user")
        self.conversation_id = str(self.conversation_id or "")
        self.run_id = str(self.run_id or "")
        self.task_id = str(self.task_id or "")
        self.source_type = str(self.source_type or "")
        self.source_id = str(self.source_id or "")
        self.memory_subtype = str(self.memory_subtype or "")
        self.content = str(self.content or "")
        self.summary = str(self.summary or "")
        self.topics = [str(item) for item in (self.topics or []) if str(item or "").strip()]
        self.stock_codes = [str(item).split(".")[0].zfill(6) for item in (self.stock_codes or []) if str(item or "").strip()]
        self.importance = _clamp(self.importance, default=0.5)
        self.confidence = _clamp(self.confidence, default=0.8)
        self.created_at = str(self.created_at or _now_text())
        self.updated_at = str(self.updated_at or self.created_at)
        self.valid_from = str(self.valid_from or "")
        self.valid_until = str(self.valid_until or "")
        self.supersedes_memory_id = str(self.supersedes_memory_id or "")
        self.metadata = dict(self.metadata or {})
        self.context_refs = [dict(item) for item in (self.context_refs or []) if isinstance(item, dict)]
        self.message_refs = [dict(item) for item in (self.message_refs or []) if isinstance(item, dict)]
        self.artifact_refs = [dict(item) for item in (self.artifact_refs or []) if isinstance(item, dict)]
        self.approval_refs = [dict(item) for item in (self.approval_refs or []) if isinstance(item, dict)]
        self.source_refs = [dict(item) for item in (self.source_refs or []) if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryRecord":
        data = dict(value or {})
        metadata = dict(data.get("metadata") or data.get("metadata_json") or {})
        phase14_type = metadata.get("phase14_memory_type")
        memory_subtype = str(data.get("memory_subtype") or data.get("memory_type") or "")
        return cls(
            memory_id=str(data.get("memory_id") or ""),
            user_id=str(data.get("user_id") or "default_user"),
            conversation_id=str(data.get("conversation_id") or ""),
            run_id=str(data.get("run_id") or metadata.get("run_id") or metadata.get("source_run_id") or ""),
            task_id=str(data.get("task_id") or metadata.get("task_id") or ""),
            source_type=str(data.get("source_type") or ""),
            source_id=str(data.get("source_id") or ""),
            memory_type=phase14_type or data.get("memory_type") or MemoryType.EPISODIC,
            memory_subtype=memory_subtype,
            scope=data.get("scope") or metadata.get("scope") or MemoryScope.CONVERSATION,
            visibility=data.get("visibility") or metadata.get("visibility") or MemoryVisibility.LLM_VISIBLE,
            status=data.get("status") or MemoryStatus.ACTIVE,
            content=str(data.get("content") or ""),
            summary=str(data.get("summary") or metadata.get("summary") or ""),
            topics=list(data.get("topics") or data.get("topics_json") or []),
            stock_codes=list(data.get("stock_codes") or data.get("stock_codes_json") or []),
            importance=data.get("importance", metadata.get("importance", 0.5)),
            confidence=data.get("confidence", metadata.get("confidence", 0.8)),
            created_at=str(data.get("created_at") or _now_text()),
            updated_at=str(data.get("updated_at") or data.get("created_at") or _now_text()),
            valid_from=str(data.get("valid_from") or ""),
            valid_until=str(data.get("valid_until") or data.get("expires_at") or ""),
            supersedes_memory_id=str(data.get("supersedes_memory_id") or ""),
            metadata=metadata,
            context_refs=list(data.get("context_refs") or metadata.get("context_refs") or []),
            message_refs=list(data.get("message_refs") or metadata.get("message_refs") or []),
            artifact_refs=list(data.get("artifact_refs") or metadata.get("artifact_refs") or []),
            approval_refs=list(data.get("approval_refs") or metadata.get("approval_refs") or []),
            source_refs=list(data.get("source_refs") or metadata.get("source_refs") or []),
        )




def _parse_memory_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def is_record_expired(record: MemoryRecord, now: datetime | None = None) -> bool:
    valid_until = _parse_memory_time(record.valid_until)
    return bool(valid_until and valid_until <= (now or datetime.now()))
