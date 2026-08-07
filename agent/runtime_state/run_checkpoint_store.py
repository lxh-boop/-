"""Persistent checkpoints for pause/resume without blocked Worker threads."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunCheckpoint:
    run_id: str
    session_id: str
    user_id: str
    status: Literal["running", "waiting_user_input", "waiting_context", "waiting_approval", "completed", "failed", "cancelled"]
    current_node_id: str = ""
    blocked_task_id: str = ""
    capability_plan: dict[str, Any] = field(default_factory=dict)
    task_states: dict[str, str] = field(default_factory=dict)
    resolved_entity_refs: list[dict[str, Any]] = field(default_factory=list)
    slot_refs: list[str] = field(default_factory=list)
    missing_parameters: list[str] = field(default_factory=list)
    missing_context_slots: list[str] = field(default_factory=list)
    pending_proposal_id: str = ""
    retry_count: int = 0
    replan_count: int = 0
    version: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunCheckpointStore:
    def __init__(self, output_dir: str | Path) -> None:
        root = Path(output_dir); root.mkdir(parents=True, exist_ok=True)
        self.path = root / "agent_runtime_state.db"
        self._lock = threading.RLock()
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_run_checkpoints (
                    run_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    checkpoint_json TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_run_checkpoints_session_status ON agent_run_checkpoints(session_id, status)"
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Open a transaction-scoped connection and always release the Windows file handle."""

        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        checkpoint.updated_at = _now()
        with self._lock, self._connection() as connection:
            previous = connection.execute(
                "SELECT version, created_at FROM agent_run_checkpoints WHERE run_id=?",
                (checkpoint.run_id,),
            ).fetchone()
            if previous:
                checkpoint.version = int(previous["version"] or 0) + 1
                checkpoint.created_at = str(previous["created_at"])
            connection.execute(
                """
                INSERT INTO agent_run_checkpoints(run_id,session_id,user_id,status,checkpoint_json,version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(run_id) DO UPDATE SET
                  session_id=excluded.session_id,user_id=excluded.user_id,status=excluded.status,
                  checkpoint_json=excluded.checkpoint_json,version=excluded.version,updated_at=excluded.updated_at
                """,
                (
                    checkpoint.run_id, checkpoint.session_id, checkpoint.user_id,
                    checkpoint.status, json.dumps(checkpoint.to_dict(), ensure_ascii=False, default=str),
                    checkpoint.version, checkpoint.created_at, checkpoint.updated_at,
                ),
            )
            connection.commit()
        return checkpoint

    def load(self, run_id: str) -> RunCheckpoint | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT checkpoint_json FROM agent_run_checkpoints WHERE run_id=?", (str(run_id),)
            ).fetchone()
        return RunCheckpoint(**json.loads(row["checkpoint_json"])) if row else None

    def pending_for_session(self, session_id: str) -> list[RunCheckpoint]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT checkpoint_json FROM agent_run_checkpoints WHERE session_id=? AND status IN ('waiting_user_input','waiting_context','waiting_approval') ORDER BY updated_at DESC",
                (str(session_id),),
            ).fetchall()
        return [RunCheckpoint(**json.loads(row["checkpoint_json"])) for row in rows]
