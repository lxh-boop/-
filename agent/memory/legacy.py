from __future__ import annotations

import math
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.schemas import AgentResponse
from database.repositories import AgentRepository


STOCK_CODE_RE = re.compile(r"(?<!\d)\d{6}(?!\d)")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,}|\d{6}")

SEMANTIC_MEMORY_TYPES = {
    "profile",
    "preference",
    "decision",
    "outcome",
    "feedback",
    "summary",
    "long_term_preference",
    "risk_preference",
    "investment_goal",
    "language_preference",
    "stable_constraint",
}

SEMANTIC_SOURCE_TYPES = {
    "action_proposal",
    "action_approval",
    "action_commit",
    "agent_run",
    "conversation_summary",
    "user_message",
    "user_feedback",
    "profile_setting",
    "manual_import",
    "confirmed_user_preference",
}

ONE_TIME_MARKERS = {
    "one_time",
    "one_time_position_operation",
    "manual_position_operation",
    "trade_preview",
    "action_proposal",
    "confirm_execute",
}

PROTOCOL_MEMORY_TYPES = {
    "profile",
    "preference",
    "decision",
    "outcome",
    "feedback",
    "summary",
}

LONG_TERM_USER_MEMORY_TYPES = {"profile", "preference"}

MEMORY_TYPE_ALIASES = {
    "long_term_preference": "preference",
    "risk_preference": "preference",
    "investment_goal": "profile",
    "language_preference": "preference",
    "stable_constraint": "preference",
    "conversation_summary": "summary",
    "agent_run": "decision",
}

AGENT_MEMORY_TYPE_VIEWS = {
    "supervisor": PROTOCOL_MEMORY_TYPES,
    "market_intelligence": {"decision", "outcome", "feedback", "summary"},
    "portfolio_analysis": {"profile", "preference", "decision", "outcome", "feedback", "summary"},
    "risk_operation": {"profile", "preference", "decision", "outcome", "feedback"},
    "reporting": PROTOCOL_MEMORY_TYPES,
}

SENSITIVE_MEMORY_KEYS = {
    "api_key",
    "authorization",
    "confirmation_token",
    "confirmation_token_hash",
    "llm_api_key",
    "password",
    "secret",
    "token",
    "tushare_token",
}

SENSITIVE_TEXT_PATTERNS = [
    re.compile(
        r"(?i)\b(api[_-]?key|authorization|confirmation[_-]?token|llm[_-]?api[_-]?key|password|secret|token|tushare[_-]?token)\b\s*[:=]\s*[^\s,;，；]+"
    ),
]


def response_to_dict(response: AgentResponse) -> dict[str, Any]:
    return asdict(response)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalise_protocol_memory_type(memory_type: str) -> str:
    lowered = str(memory_type or "").strip().lower()
    return MEMORY_TYPE_ALIASES.get(lowered, lowered)


def _sanitize_memory_text(value: Any, max_chars: int = 2000) -> str:
    text = str(value or "")
    for pattern in SENSITIVE_TEXT_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}=***", text)
    return text[:max_chars]


def _sanitize_memory_payload(value: Any, *, max_chars: int = 1200) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            text_key = str(key)
            if text_key.lower() in SENSITIVE_MEMORY_KEYS:
                out[text_key] = "***"
            else:
                out[text_key] = _sanitize_memory_payload(item, max_chars=max_chars)
        return out
    if isinstance(value, list):
        items = [_sanitize_memory_payload(item, max_chars=max_chars) for item in value[:20]]
        if len(value) > 20:
            items.append({"truncated_count": len(value) - 20})
        return items
    if isinstance(value, str):
        return _sanitize_memory_text(value, max_chars=max_chars)
    return value


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        return str(value)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _tokens(value: Any) -> set[str]:
    text = str(value or "").lower()
    tokens = set(TOKEN_RE.findall(text))
    tokens.update(STOCK_CODE_RE.findall(text))
    return tokens


def _stock_codes_from(value: Any) -> set[str]:
    if isinstance(value, list):
        return {str(item).split(".")[0].zfill(6) for item in value if str(item or "").strip()}
    return set(STOCK_CODE_RE.findall(str(value or "")))


@dataclass(frozen=True)
class MemoryWeights:
    semantic: float = 0.35
    recency: float = 0.25
    importance: float = 0.20
    entity: float = 0.20

    def __post_init__(self) -> None:
        total = self.semantic + self.recency + self.importance + self.entity
        if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            raise ValueError("memory_weights_must_sum_to_1")


@dataclass
class ScoredMemory:
    layer: str
    record: dict[str, Any]
    score: float
    score_parts: dict[str, float] = field(default_factory=dict)
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer,
            "score": round(float(self.score), 6),
            "score_parts": {key: round(float(value), 6) for key, value in self.score_parts.items()},
            "sources": list(self.sources),
            "record": dict(self.record),
        }


@dataclass(frozen=True)
class MemoryProtocolItem:
    memory_type: str
    content: str
    source_run_id: str
    user_id: str
    confidence: float = 0.8
    importance: float = 0.5
    created_at: str = ""
    expires_at: str = ""
    version: int = 1
    memory_id: str = ""
    status: str = "active"
    source_type: str = ""
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "source_run_id": self.source_run_id,
            "user_id": self.user_id,
            "confidence": round(float(self.confidence), 6),
            "importance": round(float(self.importance), 6),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "version": int(self.version),
            "status": self.status,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
        }


def memory_protocol_from_record(record: dict[str, Any]) -> MemoryProtocolItem:
    metadata = dict(record.get("metadata_json") or record.get("metadata") or {})
    protocol = dict(metadata.get("protocol") or {})
    memory_type = _normalise_protocol_memory_type(
        protocol.get("memory_type") or record.get("memory_type") or ""
    )
    confidence = protocol.get("confidence", metadata.get("confidence", 0.8))
    version = protocol.get("version", metadata.get("version", 1))
    return MemoryProtocolItem(
        memory_id=str(record.get("memory_id") or ""),
        memory_type=memory_type,
        content=str(record.get("content") or ""),
        source_run_id=str(protocol.get("source_run_id") or metadata.get("source_run_id") or record.get("source_id") or ""),
        user_id=str(record.get("user_id") or ""),
        confidence=float(confidence or 0.0),
        importance=float(record.get("importance") or 0.0),
        created_at=str(record.get("created_at") or ""),
        expires_at=str(protocol.get("expires_at") or metadata.get("expires_at") or record.get("valid_until") or ""),
        version=int(version or 1),
        status=str(record.get("status") or "active"),
        source_type=str(record.get("source_type") or ""),
        source_id=str(record.get("source_id") or ""),
        metadata=_sanitize_memory_payload(metadata),
    )


def _is_expired(record: dict[str, Any], now: datetime | None = None) -> bool:
    valid_until = _parse_time(record.get("valid_until"))
    if valid_until is None:
        return False
    return valid_until < (now or datetime.now())


def _semantic_score(query: str, record: dict[str, Any]) -> float:
    query_tokens = _tokens(query)
    record_tokens = _tokens(record.get("content"))
    for key in ("topics_json", "stock_codes_json", "company_names_json", "industries_json"):
        record_tokens.update(_tokens(record.get(key)))
    if not query_tokens or not record_tokens:
        return 0.0
    return len(query_tokens & record_tokens) / max(1, len(query_tokens | record_tokens))


def _entity_score(query: str, record: dict[str, Any]) -> float:
    query_codes = _stock_codes_from(query)
    record_codes = _stock_codes_from(record.get("stock_codes_json") or [])
    record_codes.update(_stock_codes_from(record.get("content")))
    if not query_codes:
        return 0.0
    return len(query_codes & record_codes) / max(1, len(query_codes))


def _recency_score(record: dict[str, Any], now: datetime | None = None) -> float:
    updated_at = _parse_time(record.get("updated_at") or record.get("created_at"))
    if updated_at is None:
        return 0.2
    days = max(0.0, ((now or datetime.now()) - updated_at).total_seconds() / 86400.0)
    return 1.0 / (1.0 + days / 30.0)


def _importance_score(record: dict[str, Any]) -> float:
    try:
        return min(1.0, max(0.0, float(record.get("importance") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def score_memory(
    query: str,
    record: dict[str, Any],
    *,
    weights: MemoryWeights | None = None,
    now: datetime | None = None,
) -> tuple[float, dict[str, float]]:
    weights = weights or MemoryWeights()
    parts = {
        "semantic": _semantic_score(query, record),
        "recency": _recency_score(record, now=now),
        "importance": _importance_score(record),
        "entity": _entity_score(query, record),
    }
    score = (
        weights.semantic * parts["semantic"]
        + weights.recency * parts["recency"]
        + weights.importance * parts["importance"]
        + weights.entity * parts["entity"]
    )
    return score, parts


class LayeredMemoryService:
    def __init__(self, db_path: str | Path | None = None):
        self.repo = AgentRepository(db_path)

    def get_working_memory(
        self,
        *,
        user_id: str,
        session_id: str = "",
        run_id: str = "",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if session_id:
            conversation = self.repo.store.get("conversations", {"conversation_id": session_id})
            if conversation and str(conversation.get("user_id") or "") == str(user_id):
                messages = [
                    row
                    for row in self.repo.list_messages(session_id, limit=limit)
                    if str(row.get("user_id") or "") == str(user_id)
                ]
                for row in messages[-limit:]:
                    items.append(
                        {
                            "layer": "working",
                            "kind": "message",
                            "conversation_id": session_id,
                            "role": row.get("role"),
                            "content": row.get("content"),
                            "created_at": row.get("created_at"),
                            "source_id": row.get("message_id"),
                        }
                    )
        if run_id:
            run = self.repo.store.get("agent_runs", {"run_id": run_id})
            if run and str(run.get("user_id") or "") == str(user_id):
                items.append(
                    {
                        "layer": "working",
                        "kind": "current_run",
                        "run_id": run_id,
                        "status": run.get("status"),
                        "goal": run.get("goal"),
                        "source_id": run_id,
                    }
                )
        proposals = self.repo._list_runtime(
            "action_proposals",
            filters={"user_id": user_id, "status": "pending"},
            order_by="created_at",
            limit=limit,
        )
        for proposal in proposals:
            items.append(
                {
                    "layer": "working",
                    "kind": "pending_proposal",
                    "plan_id": proposal.get("plan_id"),
                    "operation_type": proposal.get("operation_type"),
                    "created_at": proposal.get("created_at"),
                    "source_id": proposal.get("plan_id"),
                }
            )
        return items[:limit]

    def get_episodic_memory(
        self,
        *,
        user_id: str,
        query: str = "",
        session_id: str = "",
        limit: int = 8,
    ) -> list[ScoredMemory]:
        records: list[dict[str, Any]] = []
        for summary in self.repo.list_conversation_summaries(user_id=user_id, conversation_id=session_id or None, limit=limit * 2):
            records.append(
                {
                    "memory_id": summary.get("summary_id"),
                    "memory_type": "conversation_summary",
                    "content": summary.get("summary_text"),
                    "topics_json": (summary.get("metadata_json") or {}).get("topics", []),
                    "stock_codes_json": (summary.get("metadata_json") or {}).get("stock_codes", []),
                    "importance": (summary.get("metadata_json") or {}).get("importance", 0.5),
                    "updated_at": summary.get("updated_at"),
                    "source_type": "conversation_summary",
                    "source_id": summary.get("summary_id"),
                    "conversation_id": summary.get("conversation_id"),
                }
            )
        runs = self.repo._list_runtime("agent_runs", filters={"user_id": user_id}, order_by="created_at", limit=limit * 2)
        for run in runs:
            records.append(
                {
                    "memory_id": run.get("run_id"),
                    "memory_type": "agent_run",
                    "content": f"{run.get('goal') or ''} status={run.get('status') or ''}",
                    "topics_json": [],
                    "stock_codes_json": list(_stock_codes_from(run.get("goal"))),
                    "importance": 0.4 if run.get("status") == "completed" else 0.6,
                    "updated_at": run.get("finished_at") or run.get("created_at"),
                    "source_type": "agent_run",
                    "source_id": run.get("run_id"),
                    "conversation_id": run.get("conversation_id"),
                }
            )
        return self._score_records("episodic", records, query=query, limit=limit)

    def search_semantic_memory(
        self,
        *,
        user_id: str,
        query: str,
        memory_type: str | None = None,
        limit: int = 8,
    ) -> list[ScoredMemory]:
        rows = self.repo.list_memory_items(user_id=user_id, memory_type=memory_type, limit=200)
        records = [
            row
            for row in rows
            if str(row.get("user_id") or "") == str(user_id)
            and str(row.get("status") or "active") == "active"
            and not _is_expired(row)
        ]
        return self._score_records("semantic", records, query=query, limit=limit)

    def search_memories(
        self,
        *,
        user_id: str,
        query: str = "",
        memory_type: str | None = None,
        memory_types: list[str] | set[str] | tuple[str, ...] | None = None,
        min_importance: float = 0.0,
        created_after: str = "",
        created_before: str = "",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        allowed_types = {
            _normalise_protocol_memory_type(item)
            for item in (memory_types or [])
            if str(item or "").strip()
        }
        if memory_type:
            allowed_types.add(_normalise_protocol_memory_type(memory_type))
        rows = self.repo._list_runtime(
            "memory_items",
            filters={"user_id": user_id, "status": "active"},
            order_by="updated_at",
            limit=500,
        )
        after_dt = _parse_time(created_after)
        before_dt = _parse_time(created_before)
        records: list[dict[str, Any]] = []
        for row in rows:
            protocol_type = _normalise_protocol_memory_type(row.get("memory_type") or "")
            if allowed_types and protocol_type not in allowed_types:
                continue
            if _is_expired(row):
                continue
            try:
                importance = float(row.get("importance") or 0.0)
            except (TypeError, ValueError):
                importance = 0.0
            if importance < float(min_importance or 0.0):
                continue
            created_at = _parse_time(row.get("created_at"))
            if after_dt and created_at and created_at < after_dt:
                continue
            if before_dt and created_at and created_at > before_dt:
                continue
            records.append(row)
        scored = self._score_records("protocol", records, query=query, limit=limit)
        results: list[dict[str, Any]] = []
        for item in scored:
            protocol = memory_protocol_from_record(item.record)
            results.append(
                {
                    "memory": protocol.to_dict(),
                    "score": round(float(item.score), 6),
                    "score_parts": {
                        key: round(float(value), 6)
                        for key, value in item.score_parts.items()
                    },
                    "sources": list(item.sources),
                }
            )
        return results

    def memory_view_for_agent(
        self,
        *,
        user_id: str,
        query: str,
        agent_role: str,
        limit: int = 6,
    ) -> dict[str, Any]:
        role = str(agent_role or "supervisor")
        allowed = set(AGENT_MEMORY_TYPE_VIEWS.get(role, {"summary"}))
        items = self.search_memories(
            user_id=user_id,
            query=query,
            memory_types=allowed,
            limit=limit,
        )
        return {
            "agent_role": role,
            "allowed_memory_types": sorted(allowed),
            "items": items,
            "policy": {
                "least_privilege_memory_view": True,
                "sensitive_fields_redacted": True,
                "long_term_preferences_require_user_confirmation": True,
            },
        }

    def retrieve_layered_memory(
        self,
        *,
        user_id: str,
        query: str,
        session_id: str = "",
        run_id: str = "",
        limit: int = 8,
    ) -> dict[str, Any]:
        working = self.get_working_memory(user_id=user_id, session_id=session_id, run_id=run_id, limit=limit)
        episodic = [item.to_dict() for item in self.get_episodic_memory(user_id=user_id, query=query, session_id=session_id, limit=limit)]
        semantic = [item.to_dict() for item in self.search_semantic_memory(user_id=user_id, query=query, limit=limit)]
        protocol = self.search_memories(user_id=user_id, query=query, limit=limit)
        return {
            "working": working,
            "episodic": episodic,
            "semantic": semantic,
            "protocol": protocol,
            "policy": {
                "user_isolated": True,
                "expired_memories_excluded": True,
                "deleted_memories_excluded": True,
                "one_time_operations_not_promoted": True,
                "agent_inference_not_user_fact": True,
                "long_term_preferences_require_user_confirmation": True,
                "sensitive_fields_redacted": True,
            },
        }

    def remember_memory(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: str,
        source_run_id: str = "",
        source_type: str = "user_feedback",
        source_id: str = "",
        user_confirmed: bool = False,
        confidence: float = 0.8,
        importance: float = 0.5,
        expires_at: str = "",
        conversation_id: str = "",
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        supersedes_memory_id: str = "",
        change_reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        protocol_type = _normalise_protocol_memory_type(memory_type)
        if protocol_type not in PROTOCOL_MEMORY_TYPES:
            raise ValueError("unsupported_protocol_memory_type")
        metadata = dict(metadata or {})
        lowered_source = str(source_type or "").lower()
        operation_scope = str(metadata.get("operation_scope") or "").lower()
        if protocol_type in LONG_TERM_USER_MEMORY_TYPES:
            if not user_confirmed:
                raise ValueError("long_term_memory_requires_user_confirmation")
            if lowered_source not in SEMANTIC_SOURCE_TYPES or lowered_source in {
                "agent_run",
                "action_proposal",
                "action_approval",
                "action_commit",
            }:
                raise ValueError("long_term_memory_source_must_be_user_confirmed")
            if metadata.get("source_assertion") == "agent_inference" or lowered_source == "agent_inference":
                raise ValueError("agent_inference_cannot_be_user_preference")
            if operation_scope == "one_time" or lowered_source in ONE_TIME_MARKERS:
                raise ValueError("one_time_operation_cannot_be_long_term_memory")
        else:
            if operation_scope == "one_time" and protocol_type == "preference":
                raise ValueError("one_time_operation_cannot_be_long_term_memory")
        source_id = str(source_id or source_run_id or "")
        if not source_id:
            raise ValueError("memory_source_id_required")
        previous_version = 0
        if supersedes_memory_id:
            previous = self.repo.get_memory_item(supersedes_memory_id)
            if not previous or str(previous.get("user_id") or "") != str(user_id):
                raise ValueError("superseded_memory_not_found_for_user")
            previous_version = memory_protocol_from_record(previous).version
        version = max(1, previous_version + 1)
        protocol_metadata = {
            "memory_type": protocol_type,
            "source_run_id": str(source_run_id or ""),
            "confidence": min(1.0, max(0.0, float(confidence or 0.0))),
            "importance": min(1.0, max(0.0, float(importance or 0.0))),
            "created_at": _now_text(),
            "expires_at": str(expires_at or ""),
            "version": version,
            "user_confirmed": bool(user_confirmed),
            "change_reason": _sanitize_memory_text(change_reason, max_chars=500),
        }
        return self.remember_semantic_memory(
            user_id=user_id,
            content=_sanitize_memory_text(content),
            memory_type=protocol_type,
            source_type=source_type,
            source_id=source_id,
            conversation_id=conversation_id,
            topics=topics,
            stock_codes=stock_codes,
            importance=importance,
            valid_until=expires_at,
            supersedes_memory_id=supersedes_memory_id,
            metadata={
                **_sanitize_memory_payload(metadata),
                "protocol": protocol_metadata,
                "confidence": protocol_metadata["confidence"],
                "version": version,
                "source_run_id": str(source_run_id or ""),
            },
        )

    def remember_semantic_memory(
        self,
        *,
        user_id: str,
        content: str,
        memory_type: str,
        source_type: str,
        source_id: str,
        conversation_id: str = "",
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        importance: float = 0.5,
        valid_until: str = "",
        supersedes_memory_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(metadata or {})
        metadata = _sanitize_memory_payload(metadata)
        safe_content = _sanitize_memory_text(content)
        self._validate_semantic_write(
            memory_type=memory_type,
            source_type=source_type,
            source_id=source_id,
            metadata=metadata,
        )
        now = _now_text()
        if supersedes_memory_id:
            previous = self.repo.get_memory_item(supersedes_memory_id)
            if not previous or str(previous.get("user_id") or "") != str(user_id):
                raise ValueError("superseded_memory_not_found_for_user")
            self.repo.update_memory_item(
                supersedes_memory_id,
                {
                    "status": "superseded",
                    "updated_at": now,
                    "metadata": {
                        **dict(previous.get("metadata_json") or {}),
                        "superseded_by": "",
                    },
                },
            )
        memory_id = f"mem_{uuid4().hex[:12]}"
        record = self.repo.upsert_memory_item(
            {
                "memory_id": memory_id,
                "user_id": user_id,
                "conversation_id": conversation_id or None,
                "memory_type": memory_type,
                "content": safe_content,
                "topics": topics or [],
                "stock_codes": stock_codes or sorted(_stock_codes_from(safe_content)),
                "company_names": [],
                "industries": [],
                "importance": min(1.0, max(0.0, float(importance or 0.0))),
                "status": "active",
                "source_type": source_type,
                "source_id": source_id,
                "valid_until": valid_until or None,
                "created_at": now,
                "updated_at": now,
                "supersedes_memory_id": supersedes_memory_id or None,
                "metadata": {
                    **metadata,
                    "layer": "semantic",
                    "version": int(metadata.get("version") or 1),
                    "source_assertion": metadata.get("source_assertion")
                    or (
                        "user_provided"
                        if str(source_type or "").lower()
                        in {
                            "user_message",
                            "user_feedback",
                            "profile_setting",
                            "manual_import",
                            "confirmed_user_preference",
                        }
                        else "system_event"
                    ),
                    "created_by": "layered_memory_service",
                },
            }
        )
        self.repo.upsert_memory_link(
            {
                "link_id": f"mlink_{uuid4().hex[:12]}",
                "memory_id": memory_id,
                "linked_type": source_type,
                "linked_id": source_id,
                "relation": "source",
                "metadata": {"created_by": "layered_memory_service"},
            }
        )
        if supersedes_memory_id:
            previous = self.repo.get_memory_item(supersedes_memory_id) or {}
            self.repo.update_memory_item(
                supersedes_memory_id,
                {
                    "metadata": {
                        **dict(previous.get("metadata_json") or {}),
                        "superseded_by": memory_id,
                    },
                },
            )
        return record

    def delete_memory(self, *, user_id: str, memory_id: str, reason: str = "") -> bool:
        record = self.repo.get_memory_item(memory_id)
        if not record or str(record.get("user_id") or "") != str(user_id):
            return False
        metadata = dict(record.get("metadata_json") or {})
        metadata["delete_reason"] = reason
        updated = self.repo.update_memory_item(
            memory_id,
            {
                "status": "deleted",
                "updated_at": _now_text(),
                "metadata": metadata,
            },
        )
        return updated > 0

    def _score_records(
        self,
        layer: str,
        records: list[dict[str, Any]],
        *,
        query: str,
        limit: int,
    ) -> list[ScoredMemory]:
        scored: list[ScoredMemory] = []
        for record in records:
            score, parts = score_memory(query, record)
            memory_id = str(record.get("memory_id") or "")
            sources = []
            if memory_id and layer in {"semantic", "protocol"}:
                sources = self.repo.list_memory_links(memory_id)
            source_type = record.get("source_type")
            source_id = record.get("source_id")
            if source_type or source_id:
                sources.append({"linked_type": source_type, "linked_id": source_id, "relation": "source"})
            scored.append(ScoredMemory(layer=layer, record=record, score=score, score_parts=parts, sources=sources))
        scored.sort(key=lambda item: (item.score, item.score_parts.get("entity", 0.0), item.score_parts.get("importance", 0.0)), reverse=True)
        return scored[:limit]

    @staticmethod
    def _validate_semantic_write(
        *,
        memory_type: str,
        source_type: str,
        source_id: str,
        metadata: dict[str, Any],
    ) -> None:
        lowered_type = str(memory_type or "").lower()
        lowered_source = str(source_type or "").lower()
        operation_scope = str(metadata.get("operation_scope") or "").lower()
        if not source_id:
            raise ValueError("memory_source_id_required")
        if lowered_type not in SEMANTIC_MEMORY_TYPES:
            raise ValueError("unsupported_semantic_memory_type")
        if lowered_source not in SEMANTIC_SOURCE_TYPES:
            raise ValueError("unsupported_semantic_source_type")
        if lowered_source == "agent_inference" or metadata.get("source_assertion") == "agent_inference":
            raise ValueError("agent_inference_cannot_be_user_fact")
        if operation_scope == "one_time" or lowered_type in ONE_TIME_MARKERS or lowered_source in ONE_TIME_MARKERS:
            raise ValueError("one_time_operation_cannot_be_long_term_memory")
