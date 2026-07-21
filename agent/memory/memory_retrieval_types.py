from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4

from .memory_types import MemoryType


@dataclass(frozen=True)
class MemoryRetrievalRequest:
    user_id: str
    query: str = ""
    conversation_id: str = ""
    run_id: str = ""
    task_type: str = ""
    agent_role: str = "supervisor"
    entities: dict[str, Any] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    stock_codes: list[str] = field(default_factory=list)
    memory_types: list[MemoryType | str] = field(default_factory=list)
    created_after: str = ""
    created_before: str = ""
    candidate_top_n: int = 40
    relevance_threshold: float = 0.42
    token_budget: int = 360
    min_importance: float = 0.0
    include_working: bool = False
    include_long_term: bool = True
    retrieval_id: str = field(default_factory=lambda: f"memret_{uuid4().hex[:12]}")

    def normalized(self) -> "MemoryRetrievalRequest":
        return MemoryRetrievalRequest(
            user_id=str(self.user_id or "default"),
            query=str(self.query or ""),
            conversation_id=str(self.conversation_id or ""),
            run_id=str(self.run_id or ""),
            task_type=str(self.task_type or ""),
            agent_role=str(self.agent_role or "supervisor"),
            entities=dict(self.entities or {}),
            topics=[str(item) for item in (self.topics or []) if str(item or "").strip()],
            stock_codes=_normalise_codes(self.stock_codes),
            memory_types=list(self.memory_types or []),
            created_after=str(self.created_after or ""),
            created_before=str(self.created_before or ""),
            candidate_top_n=max(1, min(200, int(self.candidate_top_n or 40))),
            relevance_threshold=max(0.0, min(1.0, float(self.relevance_threshold or 0.0))),
            token_budget=max(0, int(self.token_budget or 0)),
            min_importance=max(0.0, min(1.0, float(self.min_importance or 0.0))),
            include_working=bool(self.include_working),
            include_long_term=bool(self.include_long_term),
            retrieval_id=str(self.retrieval_id or f"memret_{uuid4().hex[:12]}"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self.normalized())
        data["memory_types"] = [MemoryType.from_value(item).value for item in self.memory_types]
        return data


@dataclass(frozen=True)
class MemoryRetrievalDiagnostics:
    retrieval_id: str
    candidate_top_n: int
    candidate_count: int
    relevance_threshold: float
    threshold_pass_count: int
    selected_count: int
    token_budget: int
    token_used: int
    rejected_by_reason: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemorySelectionResult:
    selected: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: MemoryRetrievalDiagnostics | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": list(self.selected),
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else {},
        }


def _normalise_codes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip().upper().split(".", 1)[0]
        if text.isdigit() and len(text) <= 6:
            text = text.zfill(6)
        if text and text not in result:
            result.append(text)
    return result


__all__ = [
    "MemoryRetrievalDiagnostics",
    "MemoryRetrievalRequest",
    "MemorySelectionResult",
]
