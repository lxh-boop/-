from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .memory_store import SQLiteMemoryStore
from .memory_types import MemoryRecord, MemoryType
from .working_memory import WorkingMemory, is_record_expired


TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|\d{6}")


@dataclass
class MemorySearchResult:
    record: MemoryRecord
    score: float
    score_parts: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory": self.record.to_dict(),
            "score": round(float(self.score), 6),
            "score_parts": {
                key: round(float(value), 6)
                for key, value in self.score_parts.items()
            },
        }


class MemoryRetriever:
    """Retrieve and rank a broad candidate pool.

    This layer deliberately does not decide which memories enter the LLM
    context.  Context admission is performed by MemoryContextSelector using a
    relevance threshold plus entity/task/time/token-budget filtering.
    """

    def __init__(
        self,
        *,
        working_memory: WorkingMemory | None = None,
        store: SQLiteMemoryStore | None = None,
    ) -> None:
        self.working_memory = working_memory
        self.store = store

    def retrieve(
        self,
        *,
        user_id: str,
        query: str = "",
        memory_types: list[MemoryType | str] | None = None,
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        min_importance: float = 0.0,
        include_working: bool = True,
        include_long_term: bool = True,
        candidate_top_n: int = 40,
        limit: int | None = None,
    ) -> list[MemorySearchResult]:
        # ``limit`` is accepted only for source compatibility.  New production
        # callers must use candidate_top_n and perform threshold admission later.
        pool_size = max(1, min(200, int(limit if limit is not None else candidate_top_n or 40)))
        records: list[MemoryRecord] = []

        if include_working and self.working_memory:
            records.extend(
                self.working_memory.search(
                    user_id=user_id,
                    query="",
                    topics=None,
                    stock_codes=None,
                    min_importance=min_importance,
                    limit=max(20, pool_size * 2),
                )
            )

        if include_long_term and self.store:
            records.extend(
                self.store.list_records(
                    user_id=user_id,
                    memory_types=memory_types,
                    topics=None,
                    stock_codes=None,
                    min_importance=min_importance,
                    created_after=created_after,
                    created_before=created_before,
                    limit=max(40, pool_size * 4),
                )
            )

        allowed_types = {MemoryType.from_value(item) for item in (memory_types or [])}
        scored: list[MemorySearchResult] = []
        seen: set[str] = set()
        for record in records:
            if record.memory_id in seen:
                continue
            seen.add(record.memory_id)
            if allowed_types and record.memory_type not in allowed_types:
                continue
            if is_record_expired(record):
                continue
            score, parts = score_record(
                query,
                record,
                stock_codes=stock_codes,
                topics=topics,
            )
            scored.append(
                MemorySearchResult(
                    record=record,
                    score=score,
                    score_parts=parts,
                )
            )

        scored.sort(
            key=lambda item: (
                item.score,
                item.record.importance,
                item.record.updated_at,
            ),
            reverse=True,
        )
        return scored[:pool_size]


def score_record(
    query: str,
    record: MemoryRecord,
    *,
    stock_codes: list[str] | None = None,
    topics: list[str] | None = None,
) -> tuple[float, dict[str, float]]:
    semantic = _token_overlap(
        query,
        " ".join(
            [
                record.content,
                record.summary,
                record.memory_subtype,
                record.source_type,
                " ".join(record.topics),
            ]
        ),
    )
    entity = _entity_score(query, record, stock_codes=stock_codes)
    topic = _topic_score(record, topics=topics)
    importance = record.importance
    confidence = record.confidence
    score = (
        0.35 * semantic
        + 0.20 * entity
        + 0.15 * topic
        + 0.20 * importance
        + 0.10 * confidence
    )
    parts = {
        "semantic": semantic,
        "entity": entity,
        "topic": topic,
        "importance": importance,
        "confidence": confidence,
    }
    return max(0.0, min(1.0, score)), parts


def _tokens(value: Any) -> set[str]:
    return set(TOKEN_RE.findall(str(value or "").lower()))


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens))


def _entity_score(
    query: str,
    record: MemoryRecord,
    *,
    stock_codes: list[str] | None = None,
) -> float:
    query_codes = {
        item
        for item in TOKEN_RE.findall(str(query or ""))
        if item.isdigit() and len(item) == 6
    }
    query_codes.update(
        str(item).split(".")[0].zfill(6)
        for item in (stock_codes or [])
        if str(item or "").strip()
    )
    if not query_codes:
        return 0.0
    return len(query_codes & set(record.stock_codes)) / max(1, len(query_codes))


def _topic_score(record: MemoryRecord, *, topics: list[str] | None = None) -> float:
    topic_set = {str(item).lower() for item in (topics or [])}
    if not topic_set:
        return 0.0
    return len(topic_set & {item.lower() for item in record.topics}) / max(1, len(topic_set))


__all__ = ["MemoryRetriever", "MemorySearchResult", "score_record"]
