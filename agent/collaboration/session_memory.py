from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import GraphAgentTask, SessionMemoryItem, new_id, now_text


DEFAULT_TTL_HOURS = 24
_MAX_VALUE_CHARS = 80_000
_SECRET_KEYS = {
    "api_key",
    "llm_api_key",
    "password",
    "secret",
    "authorization",
    "cookie",
    "confirmation_token",
    "confirmation_token_hash",
    "raw_payload",
    "raw_tool_payload",
    "private_chain_of_thought",
    "chain_of_thought",
    "reasoning_content",
    "traceback",
    "stack_trace",
}
_SOURCE_PRIORITY = {
    "user_message": 100,
    "user_clarification": 100,
    "user_confirmation": 100,
    "entity_resolution": 85,
    "system_context": 80,
    "agent_result": 65,
    "agent_inference": 45,
    "tool_result": 35,
    "unknown": 10,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _safe_jsonable(value: Any, *, depth: int = 0) -> Any:
    if depth > 10:
        return "<truncated>"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.lower() in _SECRET_KEYS:
                continue
            result[key] = _safe_jsonable(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_jsonable(item, depth=depth + 1) for item in list(value)[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
            return value[:_MAX_VALUE_CHARS] + "...<truncated>"
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _safe_jsonable(value.to_dict(), depth=depth + 1)
    text = str(value)
    return text[:_MAX_VALUE_CHARS] + ("...<truncated>" if len(text) > _MAX_VALUE_CHARS else "")


def _dumps(value: Any) -> str:
    return json.dumps(_safe_jsonable(value), ensure_ascii=False, sort_keys=True, default=str)


def _loads(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value if value is not None else default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _summary_from_value(value: Any, *, max_chars: int = 500) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        preferred = value.get("summary") or value.get("message") or value.get("description")
        text = str(preferred) if preferred else _dumps(value)
    else:
        text = _dumps(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars] + ("…" if len(text) > max_chars else "")


def _tokens(text: str) -> set[str]:
    lowered = str(text or "").lower()
    english = set(re.findall(r"[a-z0-9_.-]{2,}", lowered))
    chinese = set(re.findall(r"[\u4e00-\u9fff]{2,}", lowered))
    return english | chinese


@dataclass(frozen=True)
class MemoryPutOutcome:
    item: SessionMemoryItem
    changed: bool
    conflict: bool = False
    ignored_reason: str = ""


class SessionMemoryStore:
    """SQLite-backed, conversation-scoped temporary memory.

    It is intentionally separate from long-term user memory. Every item has a
    session_id and expires automatically. New versions are appended instead of
    destructively overwriting older facts.
    """

    def __init__(
        self,
        output_dir: str | Path = "outputs",
        *,
        db_path: str | Path | None = None,
        default_ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.db_path = Path(db_path) if db_path else self.output_dir / "session_memory" / "session_memory.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.default_ttl_hours = max(1, int(default_ttl_hours or DEFAULT_TTL_HOURS))
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS session_memory_items (
                    memory_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    value_type TEXT NOT NULL DEFAULT 'json',
                    summary TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    source_ref TEXT NOT NULL DEFAULT '',
                    confirmed INTEGER NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 0.8,
                    version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(session_id, memory_key, version)
                );

                CREATE INDEX IF NOT EXISTS idx_session_memory_lookup
                ON session_memory_items(session_id, memory_key, status, version DESC);

                CREATE INDEX IF NOT EXISTS idx_session_memory_expiry
                ON session_memory_items(expires_at, status);

                CREATE TABLE IF NOT EXISTS session_memory_access_log (
                    access_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    operation TEXT NOT NULL,
                    query_text TEXT NOT NULL DEFAULT '',
                    matched_keys_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_session_memory_access_task
                ON session_memory_access_log(session_id, run_id, task_id, created_at);

                CREATE TABLE IF NOT EXISTS session_waiting_tasks (
                    waiting_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    missing_keys_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'waiting_context',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    UNIQUE(session_id, task_id, status)
                );

                CREATE INDEX IF NOT EXISTS idx_waiting_tasks_session
                ON session_waiting_tasks(session_id, status, updated_at);
                """
            )

    def _expires_at(self, ttl_hours: int | None = None) -> str:
        hours = max(1, int(ttl_hours or self.default_ttl_hours))
        return (_utcnow() + timedelta(hours=hours)).isoformat(timespec="seconds")

    def _row_to_item(self, row: sqlite3.Row | dict[str, Any]) -> SessionMemoryItem:
        data = dict(row)
        return SessionMemoryItem(
            memory_id=str(data.get("memory_id") or ""),
            session_id=str(data.get("session_id") or ""),
            key=str(data.get("memory_key") or data.get("key") or ""),
            value=_loads(data.get("value_json"), default={}),
            value_type=str(data.get("value_type") or "json"),
            summary=str(data.get("summary") or ""),
            source_type=str(data.get("source_type") or ""),
            source_ref=str(data.get("source_ref") or ""),
            confirmed=bool(data.get("confirmed")),
            confidence=float(data.get("confidence") or 0.0),
            version=int(data.get("version") or 1),
            status=str(data.get("status") or "active"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
            expires_at=str(data.get("expires_at") or ""),
        )

    def cleanup_expired(self) -> dict[str, int]:
        now = _utcnow().isoformat(timespec="seconds")
        with self._lock, self._connect() as connection:
            memory_count = connection.execute(
                "UPDATE session_memory_items SET status='expired', updated_at=? "
                "WHERE status='active' AND expires_at <= ?",
                (now, now),
            ).rowcount
            waiting_count = connection.execute(
                "UPDATE session_waiting_tasks SET status='expired', updated_at=? "
                "WHERE status='waiting_context' AND expires_at <= ?",
                (now, now),
            ).rowcount
        return {"memory_items": int(memory_count or 0), "waiting_tasks": int(waiting_count or 0)}

    def get(self, session_id: str, key: str, *, include_expired: bool = False) -> SessionMemoryItem | None:
        self.cleanup_expired()
        status_clause = "" if include_expired else "AND status='active'"
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM session_memory_items WHERE session_id=? AND memory_key=? "
                f"{status_clause} ORDER BY version DESC, updated_at DESC LIMIT 1",
                (str(session_id or ""), str(key or "")),
            ).fetchone()
        return self._row_to_item(row) if row else None

    def put(
        self,
        *,
        session_id: str,
        key: str,
        value: Any,
        value_type: str = "json",
        summary: str = "",
        source_type: str = "unknown",
        source_ref: str = "",
        confirmed: bool = False,
        confidence: float = 0.8,
        ttl_hours: int | None = None,
    ) -> MemoryPutOutcome:
        session = str(session_id or "").strip()
        memory_key = str(key or "").strip()
        if not session:
            raise ValueError("session_id is required")
        if not memory_key:
            raise ValueError("memory key is required")
        safe_value = _safe_jsonable(value)
        value_json = _dumps(safe_value)
        source = str(source_type or "unknown")
        new_summary = str(summary or "").strip() or _summary_from_value(safe_value)
        now = now_text()
        expires = self._expires_at(ttl_hours)
        try:
            new_confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            new_confidence = 0.8

        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM session_memory_items WHERE session_id=? AND memory_key=? "
                "AND status='active' ORDER BY version DESC LIMIT 1",
                (session, memory_key),
            ).fetchone()
            previous = self._row_to_item(row) if row else None
            if previous and _dumps(previous.value) == value_json:
                connection.execute(
                    "UPDATE session_memory_items SET updated_at=?, expires_at=?, confidence=MAX(confidence, ?), "
                    "confirmed=MAX(confirmed, ?), summary=CASE WHEN summary='' THEN ? ELSE summary END "
                    "WHERE memory_id=?",
                    (now, expires, new_confidence, int(bool(confirmed)), new_summary, previous.memory_id),
                )
                refreshed = SessionMemoryItem(
                    memory_id=previous.memory_id,
                    session_id=previous.session_id,
                    key=previous.key,
                    value=previous.value,
                    value_type=previous.value_type,
                    summary=previous.summary or new_summary,
                    source_type=previous.source_type,
                    source_ref=previous.source_ref,
                    confirmed=previous.confirmed or bool(confirmed),
                    confidence=max(previous.confidence, new_confidence),
                    version=previous.version,
                    status=previous.status,
                    created_at=previous.created_at,
                    updated_at=now,
                    expires_at=expires,
                )
                connection.commit()
                return MemoryPutOutcome(item=refreshed, changed=False)

            conflict = False
            if previous:
                old_priority = _SOURCE_PRIORITY.get(previous.source_type, _SOURCE_PRIORITY["unknown"])
                new_priority = _SOURCE_PRIORITY.get(source, _SOURCE_PRIORITY["unknown"])
                if previous.confirmed and not confirmed and new_priority < old_priority:
                    return MemoryPutOutcome(
                        item=previous,
                        changed=False,
                        conflict=True,
                        ignored_reason="lower_priority_update_cannot_replace_confirmed_fact",
                    )
                conflict = previous.confirmed and bool(confirmed)
                next_version = previous.version + 1
                connection.execute(
                    "UPDATE session_memory_items SET status='superseded', updated_at=? WHERE memory_id=?",
                    (now, previous.memory_id),
                )
            else:
                next_version = 1

            item = SessionMemoryItem(
                memory_id=new_id("smem"),
                session_id=session,
                key=memory_key,
                value=safe_value,
                value_type=value_type,
                summary=new_summary,
                source_type=source,
                source_ref=source_ref,
                confirmed=confirmed,
                confidence=new_confidence,
                version=next_version,
                status="active",
                created_at=now,
                updated_at=now,
                expires_at=expires,
            )
            connection.execute(
                "INSERT INTO session_memory_items (memory_id, session_id, memory_key, value_json, value_type, "
                "summary, source_type, source_ref, confirmed, confidence, version, status, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item.memory_id,
                    item.session_id,
                    item.key,
                    value_json,
                    item.value_type,
                    item.summary,
                    item.source_type,
                    item.source_ref,
                    int(item.confirmed),
                    item.confidence,
                    item.version,
                    item.status,
                    item.created_at,
                    item.updated_at,
                    item.expires_at,
                ),
            )
            connection.commit()
            return MemoryPutOutcome(item=item, changed=True, conflict=conflict)

    def list_latest(self, session_id: str, *, limit: int = 100) -> list[SessionMemoryItem]:
        self.cleanup_expired()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT item.* FROM session_memory_items item "
                "JOIN (SELECT memory_key, MAX(version) AS version FROM session_memory_items "
                "WHERE session_id=? AND status='active' GROUP BY memory_key) latest "
                "ON item.memory_key=latest.memory_key AND item.version=latest.version "
                "WHERE item.session_id=? AND item.status='active' "
                "ORDER BY item.confirmed DESC, item.updated_at DESC LIMIT ?",
                (str(session_id or ""), str(session_id or ""), max(1, min(1000, int(limit or 100)))),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def search(
        self,
        session_id: str,
        query: str,
        *,
        limit: int = 8,
        run_id: str = "",
        task_id: str = "",
        agent_id: str = "",
    ) -> list[SessionMemoryItem]:
        records = self.list_latest(session_id, limit=1000)
        query_text = str(query or "").strip().lower()
        query_tokens = _tokens(query_text)
        scored: list[tuple[float, SessionMemoryItem]] = []
        for item in records:
            haystack = " ".join([item.key, item.summary, _dumps(item.value)]).lower()
            tokens = _tokens(haystack)
            overlap = len(query_tokens & tokens) / max(1, len(query_tokens)) if query_tokens else 0.0
            contains = 1.0 if query_text and query_text in haystack else 0.0
            key_hit = 1.0 if item.key.lower() == query_text else 0.0
            score = key_hit * 5.0 + contains * 2.0 + overlap * 3.0 + (0.4 if item.confirmed else 0.0) + item.confidence * 0.2
            if not query_text or score > 0.0:
                scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
        result = [item for _, item in scored[: max(1, min(50, int(limit or 8)))]]
        self.log_access(
            session_id=session_id,
            run_id=run_id,
            task_id=task_id,
            agent_id=agent_id,
            operation="search",
            query_text=query,
            matched_keys=[item.key for item in result],
        )
        return result

    def build_summary(
        self,
        session_id: str,
        *,
        task_objective: str = "",
        max_chars: int = 3600,
        limit: int = 18,
    ) -> str:
        """Build a compact specialist cache view, not a conversation transcript.

        Locked GraphRefs are authoritative for active financial objects;
        ArtifactStore is authoritative for full results. Session memory only
        contributes compact task-local facts and references.
        """

        records = self.list_latest(session_id, limit=500)
        objective_tokens = _tokens(task_objective)
        priority = {
            "active_goal": 8.0,
            "active_graph_refs": 9.0,
            "latest_result_ref": 7.0,
            "latest_result_summary": 6.5,
            "completed_dimensions": 6.0,
            "missing_dimensions": 6.0,
            "last_user_message": 4.0,
        }
        ranked: list[tuple[float, SessionMemoryItem]] = []
        for item in records:
            # Per-turn transcript mirrors are not injected automatically.  The
            # authoritative turn resolver already supplies relevant turns.
            if item.key.startswith("turn:"):
                continue
            tokens = _tokens(" ".join([item.key, item.summary, _dumps(item.value)]))
            relevance = (
                len(objective_tokens & tokens) / max(1, len(objective_tokens))
                if objective_tokens
                else 0.0
            )
            base = priority.get(item.key, 0.0)
            if item.key.startswith("agent_result:"):
                base -= 1.0
            score = (
                base
                + relevance * 5.0
                + (1.0 if item.confirmed else 0.0)
                + item.confidence
                + min(item.version, 5) * 0.02
            )
            ranked.append((score, item))
        ranked.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)

        budget = max(600, min(int(max_chars or 3600), 3600))
        lines: list[str] = []
        used = 0
        seen_text: set[str] = set()
        for _, item in ranked[: max(1, min(24, int(limit or 18)))]:
            marker = "confirmed" if item.confirmed else "unconfirmed"
            per_item_limit = 320 if item.key.startswith("agent_result:") else 650
            body = item.summary or _summary_from_value(item.value, max_chars=per_item_limit)
            body = str(body or "")[:per_item_limit]
            signature = " ".join(body.lower().split())[:180]
            if signature and signature in seen_text:
                continue
            if signature:
                seen_text.add(signature)
            line = f"- {item.key} ({marker}, v{item.version}): {body}"
            if used + len(line) + 1 > budget:
                continue
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) if lines else "No reusable specialist working context is available."

    def log_access(
        self,
        *,
        session_id: str,
        run_id: str,
        task_id: str,
        agent_id: str,
        operation: str,
        query_text: str = "",
        matched_keys: Iterable[str] = (),
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO session_memory_access_log (access_id, session_id, run_id, task_id, agent_id, operation, "
                "query_text, matched_keys_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    new_id("mem_access"),
                    str(session_id or ""),
                    str(run_id or ""),
                    str(task_id or ""),
                    str(agent_id or ""),
                    str(operation or ""),
                    str(query_text or "")[:1000],
                    _dumps(list(matched_keys)[:50]),
                    now_text(),
                ),
            )

    def access_count(self, session_id: str, task_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM session_memory_access_log WHERE session_id=? AND task_id=?",
                (str(session_id or ""), str(task_id or "")),
            ).fetchone()
        return int(row["count"] if row else 0)

    def register_waiting_task(
        self,
        task: GraphAgentTask,
        missing_keys: list[str],
        *,
        ttl_hours: int | None = None,
    ) -> str:
        waiting_id = new_id("waiting")
        now = now_text()
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE session_waiting_tasks SET status='superseded', updated_at=? "
                "WHERE session_id=? AND task_id=? AND status='waiting_context'",
                (now, task.session_id, task.task_id),
            )
            connection.execute(
                "INSERT INTO session_waiting_tasks (waiting_id, session_id, run_id, task_id, task_json, "
                "missing_keys_json, status, attempt, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'waiting_context', ?, ?, ?, ?)",
                (
                    waiting_id,
                    task.session_id,
                    task.run_id,
                    task.task_id,
                    _dumps(task.to_dict()),
                    _dumps(list(dict.fromkeys(str(item) for item in missing_keys if str(item).strip()))),
                    task.attempt,
                    now,
                    now,
                    self._expires_at(ttl_hours),
                ),
            )
        return waiting_id

    def list_waiting_tasks(self, session_id: str) -> list[dict[str, Any]]:
        self.cleanup_expired()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM session_waiting_tasks WHERE session_id=? AND status='waiting_context' "
                "ORDER BY created_at ASC",
                (str(session_id or ""),),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            data["task"] = _loads(data.pop("task_json", "{}"), default={})
            data["missing_keys"] = _loads(data.pop("missing_keys_json", "[]"), default=[])
            result.append(data)
        return result

    def mark_waiting_resumed(self, waiting_id: str, *, new_run_id: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE session_waiting_tasks SET status='resumed', updated_at=?, run_id=CASE WHEN ?='' THEN run_id ELSE ? END "
                "WHERE waiting_id=?",
                (now_text(), str(new_run_id or ""), str(new_run_id or ""), str(waiting_id or "")),
            )

    def clear_session(self, session_id: str, *, hard: bool = True) -> dict[str, int]:
        session = str(session_id or "")
        with self._lock, self._connect() as connection:
            if hard:
                access = connection.execute("DELETE FROM session_memory_access_log WHERE session_id=?", (session,)).rowcount
                waiting = connection.execute("DELETE FROM session_waiting_tasks WHERE session_id=?", (session,)).rowcount
                memory = connection.execute("DELETE FROM session_memory_items WHERE session_id=?", (session,)).rowcount
            else:
                now = now_text()
                memory = connection.execute(
                    "UPDATE session_memory_items SET status='expired', updated_at=? WHERE session_id=? AND status='active'",
                    (now, session),
                ).rowcount
                waiting = connection.execute(
                    "UPDATE session_waiting_tasks SET status='expired', updated_at=? WHERE session_id=? AND status='waiting_context'",
                    (now, session),
                ).rowcount
                access = 0
        return {"memory_items": int(memory or 0), "waiting_tasks": int(waiting or 0), "access_logs": int(access or 0)}

    def stats(self, session_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            memory = connection.execute(
                "SELECT COUNT(*) AS count FROM session_memory_items WHERE session_id=? AND status='active'",
                (str(session_id or ""),),
            ).fetchone()
            waiting = connection.execute(
                "SELECT COUNT(*) AS count FROM session_waiting_tasks WHERE session_id=? AND status='waiting_context'",
                (str(session_id or ""),),
            ).fetchone()
        return {
            "session_id": str(session_id or ""),
            "active_memory_count": int(memory["count"] if memory else 0),
            "waiting_task_count": int(waiting["count"] if waiting else 0),
            "temporary": True,
            "default_ttl_hours": self.default_ttl_hours,
            "store": "outputs/session_memory/session_memory.sqlite",
        }
