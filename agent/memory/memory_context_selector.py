from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from .memory_retrieval_types import (
    MemoryRetrievalDiagnostics,
    MemoryRetrievalRequest,
    MemorySelectionResult,
)
from .memory_retriever import MemorySearchResult
from .memory_types import MemoryRecord, MemoryType

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")
_STOCK_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")


def estimate_tokens(value: Any) -> int:
    text = str(value or "")
    if not text:
        return 0
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, int(ascii_count / 4) + int(non_ascii_count / 2))


def truncate_text_to_tokens(value: Any, max_tokens: int) -> str:
    text = str(value or "")
    budget = max(1, int(max_tokens or 1))
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + "…"


class MemoryContextSelector:
    """Select context memories from one already-retrieved candidate pool.

    The selector never queries storage.  It applies relevance thresholding,
    entity/task/time checks, and then packs passing summaries into a token
    budget.  Therefore the final context may contain zero items.
    """

    def select(
        self,
        candidates: list[MemorySearchResult],
        request: MemoryRetrievalRequest,
    ) -> MemorySelectionResult:
        req = request.normalized()
        rejected: Counter[str] = Counter()
        passing: list[dict[str, Any]] = []

        query_codes = set(req.stock_codes)
        query_codes.update(_STOCK_RE.findall(req.query))
        query_entities = _entity_terms(req.entities)
        task_terms = _tokens(" ".join([req.task_type, req.agent_role, req.query]))

        for candidate in candidates:
            record = candidate.record
            if not _is_visible_for_role(record, req.agent_role):
                rejected["role_visibility"] += 1
                continue

            entity_score, entity_reject = _entity_score(record, query_codes, query_entities)
            if entity_reject:
                rejected["entity_mismatch"] += 1
                continue

            task_score, task_reject = _task_score(record, req.task_type, task_terms)
            if task_reject:
                rejected["task_mismatch"] += 1
                continue

            time_score = _time_score(record)
            final_score = _final_score(
                base_score=candidate.score,
                entity_score=entity_score,
                task_score=task_score,
                time_score=time_score,
                importance=record.importance,
            )
            if final_score < req.relevance_threshold:
                rejected["below_threshold"] += 1
                continue

            summary = _context_summary(record)
            token_estimate = estimate_tokens(summary)
            passing.append(
                {
                    "record": record,
                    "summary": summary,
                    "score": final_score,
                    "token_estimate": token_estimate,
                    "score_parts": {
                        **dict(candidate.score_parts or {}),
                        "base_retrieval": round(float(candidate.score), 6),
                        "entity_filter": round(entity_score, 6),
                        "task_filter": round(task_score, 6),
                        "time_decay": round(time_score, 6),
                        "final": round(final_score, 6),
                    },
                }
            )

        passing.sort(
            key=lambda item: (
                float(item["score"]),
                float(item["record"].importance),
                str(item["record"].updated_at),
            ),
            reverse=True,
        )

        selected: list[dict[str, Any]] = []
        token_used = 0
        budget = req.token_budget
        for item in passing:
            summary = str(item["summary"] or "")
            token_estimate = int(item["token_estimate"] or 0)
            if budget <= 0:
                rejected["token_budget"] += 1
                continue
            remaining = budget - token_used
            if remaining <= 0:
                rejected["token_budget"] += 1
                continue
            if token_estimate > remaining:
                if not selected and remaining >= 40:
                    summary = truncate_text_to_tokens(summary, max(1, remaining - 1))
                    token_estimate = estimate_tokens(summary)
                    while summary and token_estimate > remaining:
                        summary = summary[:-1]
                        token_estimate = estimate_tokens(summary)
                else:
                    rejected["token_budget"] += 1
                    continue

            record: MemoryRecord = item["record"]
            selected.append(
                {
                    "memory": {
                        "memory_id": record.memory_id,
                        "memory_type": record.memory_type.value,
                        "memory_subtype": record.memory_subtype,
                        "scope": record.scope.value,
                        "summary": summary,
                        "topics": list(record.topics)[:10],
                        "stock_codes": list(record.stock_codes)[:10],
                        "importance": round(float(record.importance), 6),
                        "confidence": round(float(record.confidence), 6),
                        "source_type": record.source_type,
                        "source_id": record.source_id,
                        "updated_at": record.updated_at,
                        "source_refs": list(record.source_refs)[:10],
                    },
                    "score": round(float(item["score"]), 6),
                    "score_parts": dict(item["score_parts"]),
                    "token_estimate": token_estimate,
                    "selection_reasons": _selection_reasons(item["score_parts"]),
                }
            )
            token_used += token_estimate

        diagnostics = MemoryRetrievalDiagnostics(
            retrieval_id=req.retrieval_id,
            candidate_top_n=req.candidate_top_n,
            candidate_count=len(candidates),
            relevance_threshold=req.relevance_threshold,
            threshold_pass_count=len(passing),
            selected_count=len(selected),
            token_budget=budget,
            token_used=token_used,
            rejected_by_reason=dict(rejected),
        )
        return MemorySelectionResult(selected=selected, diagnostics=diagnostics)


def _tokens(value: Any) -> set[str]:
    return {item.lower() for item in _TOKEN_RE.findall(str(value or ""))}


def _entity_terms(value: Any) -> set[str]:
    if isinstance(value, dict):
        terms: set[str] = set()
        for key, item in value.items():
            terms.update(_tokens(key))
            terms.update(_entity_terms(item))
        return terms
    if isinstance(value, (list, tuple, set)):
        terms: set[str] = set()
        for item in value:
            terms.update(_entity_terms(item))
        return terms
    return _tokens(value)


def _entity_score(
    record: MemoryRecord,
    query_codes: set[str],
    query_entities: set[str],
) -> tuple[float, bool]:
    record_codes = {str(item).split(".", 1)[0].zfill(6) for item in record.stock_codes}
    if query_codes and record_codes and not (query_codes & record_codes):
        return 0.0, True
    code_score = 1.0 if query_codes and (query_codes & record_codes) else (0.55 if not record_codes else 0.35)

    record_entities = _tokens(" ".join([record.summary, record.memory_subtype, *record.topics]))
    if not query_entities:
        text_score = 0.5
    elif not record_entities:
        text_score = 0.35
    else:
        text_score = len(query_entities & record_entities) / max(1, len(query_entities))
    return max(code_score, text_score), False


def _task_score(record: MemoryRecord, task_type: str, task_terms: set[str]) -> tuple[float, bool]:
    metadata = dict(record.metadata or {})
    declared = metadata.get("task_types") or metadata.get("intents") or metadata.get("tasks") or []
    if isinstance(declared, str):
        declared = [declared]
    declared_terms = _tokens(" ".join(str(item) for item in declared))
    record_terms = _tokens(" ".join([record.memory_subtype, record.source_type, *record.topics, record.summary]))

    if task_type and declared_terms and not (_tokens(task_type) & declared_terms):
        return 0.0, True
    if not task_terms:
        return 0.5, False
    overlap = len(task_terms & record_terms) / max(1, len(task_terms))
    if declared_terms:
        overlap = max(overlap, len(task_terms & declared_terms) / max(1, len(task_terms)))
    return max(0.35, min(1.0, overlap)), False


def _parse_time(value: str) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _time_score(record: MemoryRecord) -> float:
    stamp = _parse_time(record.updated_at or record.created_at)
    if stamp is None:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds() / 86400.0)
    if record.memory_type == MemoryType.SEMANTIC or record.memory_subtype in {
        "preference",
        "risk_preference",
        "stable_constraint",
        "profile",
        "investment_goal",
    }:
        half_life = 720.0
    elif record.memory_type == MemoryType.EPISODIC:
        half_life = 120.0
    else:
        half_life = 240.0
    return max(0.0, min(1.0, math.exp(-math.log(2.0) * age_days / half_life)))


def _final_score(
    *,
    base_score: float,
    entity_score: float,
    task_score: float,
    time_score: float,
    importance: float,
) -> float:
    score = (
        0.55 * float(base_score)
        + 0.15 * entity_score
        + 0.15 * task_score
        + 0.10 * time_score
        + 0.05 * float(importance)
    )
    return max(0.0, min(1.0, score))


def _context_summary(record: MemoryRecord) -> str:
    summary = str(record.summary or record.content or "").strip()
    prefix: list[str] = []
    if record.memory_subtype:
        prefix.append(record.memory_subtype)
    if record.stock_codes:
        prefix.append("stocks=" + ",".join(record.stock_codes[:6]))
    if prefix:
        summary = f"[{' | '.join(prefix)}] {summary}"
    return summary[:1800]


def _selection_reasons(parts: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in ("entity_filter", "task_filter", "time_decay", "importance", "semantic"):
        try:
            value = float(parts.get(key) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value >= 0.65:
            reasons.append(f"{key}:{value:.2f}")
    return reasons[:5]


def _is_visible_for_role(record: MemoryRecord, role: str) -> bool:
    metadata = dict(record.metadata or {})
    allowed_roles = metadata.get("allowed_agent_roles") or metadata.get("agent_roles") or []
    if isinstance(allowed_roles, str):
        allowed_roles = [allowed_roles]
    if allowed_roles and str(role or "supervisor") not in {str(item) for item in allowed_roles}:
        return False
    return True


__all__ = ["MemoryContextSelector"]
