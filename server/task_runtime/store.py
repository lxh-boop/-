from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.api.serialization import decode_transport, encode_transport

ACTIVE_STATUSES = {"queued", "running", "cancelling"}
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "timed_out", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class TaskStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner_id TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    request_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    error_json TEXT,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    timeout_seconds INTEGER NOT NULL DEFAULT 99600,
                    max_retries INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    worker_pid INTEGER,
                    acknowledged_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_task_runs_lookup
                    ON task_runs(owner_id, session_id, task_type, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_task_runs_status
                    ON task_runs(status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS task_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES task_runs(task_id)
                );
                CREATE INDEX IF NOT EXISTS idx_task_events_task
                    ON task_events(task_id, sequence);
                """
            )

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(encode_transport(value), ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _load(value: str | None) -> Any:
        if not value:
            return None
        return decode_transport(json.loads(value))

    def create(
        self,
        *,
        task_id: str,
        task_type: str,
        request: dict[str, Any],
        owner_id: str = "",
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
        timeout_seconds: int = 99600,
        max_retries: int = 0,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO task_runs(
                    task_id, task_type, status, owner_id, session_id, request_json,
                    metadata_json, created_at, updated_at, timeout_seconds, max_retries
                ) VALUES(?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    task_type,
                    owner_id,
                    session_id,
                    self._dump(request),
                    self._dump(metadata or {}),
                    now,
                    now,
                    max(1, int(timeout_seconds)),
                    max(0, int(max_retries)),
                ),
            )
        self.add_event(task_id, "queued", {"message": "任务已进入队列", "progress": 0})
        return self.get(task_id)

    def get(self, task_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM task_runs WHERE task_id = ?", (str(task_id),)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        item = dict(row)
        for key in ("request_json", "metadata_json", "result_json", "error_json"):
            item[key[:-5]] = self._load(item.pop(key, None))
        item["cancel_requested"] = bool(item.get("cancel_requested"))
        item["progress"] = float(item.get("progress") or 0)
        return item

    def list(
        self,
        *,
        owner_id: str = "",
        session_id: str = "",
        task_type: str = "",
        active_only: bool = False,
        unacknowledged_only: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if owner_id:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if task_type:
            clauses.append("task_type = ?")
            params.append(task_type)
        if active_only:
            clauses.append("status IN ('queued','running','cancelling')")
        if unacknowledged_only:
            clauses.append("acknowledged_at IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 200)))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT task_id FROM task_runs{where} ORDER BY created_at DESC LIMIT ?",
                tuple(params),
            ).fetchall()
        return [self.get(str(row["task_id"])) for row in rows]

    def update(self, task_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {
            "status", "progress", "message", "started_at", "finished_at", "updated_at",
            "timeout_seconds", "max_retries", "attempt", "cancel_requested", "worker_pid",
            "acknowledged_at",
        }
        values: dict[str, Any] = {key: value for key, value in fields.items() if key in allowed}
        if "result" in fields:
            values["result_json"] = self._dump(fields["result"])
        if "error" in fields:
            values["error_json"] = self._dump(fields["error"])
        if "metadata" in fields:
            values["metadata_json"] = self._dump(fields["metadata"])
        values["updated_at"] = fields.get("updated_at") or utc_now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE task_runs SET {assignments} WHERE task_id = ?",
                tuple(values.values()) + (str(task_id),),
            )
        return self.get(task_id)

    def request_cancel(self, task_id: str) -> dict[str, Any]:
        current = self.get(task_id)
        if current["status"] in TERMINAL_STATUSES:
            return current
        row = self.update(task_id, cancel_requested=1, status="cancelling", message="正在取消任务")
        self.add_event(task_id, "cancel_requested", {"message": "已收到取消请求"})
        return row

    def acknowledge(self, task_id: str) -> dict[str, Any]:
        return self.update(task_id, acknowledged_at=utc_now())

    def add_event(self, task_id: str, event_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO task_events(task_id, event_type, data_json, created_at) VALUES(?, ?, ?, ?)",
                (str(task_id), str(event_type), self._dump(data or {}), now),
            )
            sequence = int(cursor.lastrowid)
        return {"sequence": sequence, "task_id": str(task_id), "event_type": str(event_type), "data": data or {}, "created_at": now}

    def events(self, task_id: str, *, after_sequence: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT sequence, task_id, event_type, data_json, created_at
                   FROM task_events WHERE task_id = ? AND sequence > ?
                   ORDER BY sequence ASC LIMIT ?""",
                (str(task_id), max(0, int(after_sequence)), max(1, min(int(limit), 1000))),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "task_id": str(row["task_id"]),
                "event_type": str(row["event_type"]),
                "data": self._load(row["data_json"]) or {},
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def recover_interrupted(self) -> list[str]:
        now = utc_now()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id FROM task_runs WHERE status IN ('queued','running','cancelling')"
            ).fetchall()
            ids = [str(row["task_id"]) for row in rows]
            if ids:
                conn.execute(
                    """UPDATE task_runs SET status='interrupted', finished_at=?, updated_at=?,
                       message='FastAPI 服务重启，原任务已终止', worker_pid=NULL
                       WHERE status IN ('queued','running','cancelling')""",
                    (now, now),
                )
        for task_id in ids:
            self.add_event(task_id, "interrupted", {"message": "FastAPI 服务重启，原任务已终止"})
        return ids
