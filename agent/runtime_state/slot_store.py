"""Run-scoped information slot store."""

from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SlotRecord:
    slot_record_id: str
    run_id: str
    task_id: str
    contract_id: str
    slot_id: str
    schema_id: str
    value_ref: str
    safe_summary: str = ""
    value: Any = None
    entity_refs: list[dict[str, Any]] = field(default_factory=list)
    provenance_refs: list[str] = field(default_factory=list)
    authority_level: str = "worker_verified"
    freshness_time: str = ""
    completeness_status: str = "complete"
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RunSlotStore:
    """Persist normalized slots without exposing Worker internal state."""

    def __init__(self, output_dir: str | Path) -> None:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "agent_runtime_state.db"
        self._lock = threading.RLock()
        self._init_schema()

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

    def _init_schema(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_run_slots (
                    slot_record_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    contract_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL,
                    schema_id TEXT NOT NULL,
                    value_ref TEXT NOT NULL,
                    safe_summary TEXT NOT NULL,
                    value_json TEXT,
                    entity_refs_json TEXT NOT NULL,
                    provenance_refs_json TEXT NOT NULL,
                    authority_level TEXT NOT NULL,
                    freshness_time TEXT NOT NULL,
                    completeness_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_run_slots_run_slot ON agent_run_slots(run_id, slot_id)"
            )
            connection.commit()

    def publish(
        self,
        *,
        run_id: str,
        task_id: str,
        contract_id: str,
        slot_id: str,
        value: Any,
        schema_id: str = "",
        safe_summary: str = "",
        entity_refs: list[dict[str, Any]] | None = None,
        provenance_refs: list[str] | None = None,
        authority_level: str = "worker_verified",
        freshness_time: str = "",
        completeness_status: str = "complete",
    ) -> SlotRecord:
        record = SlotRecord(
            slot_record_id=f"slot_{uuid4().hex[:16]}",
            run_id=str(run_id), task_id=str(task_id), contract_id=str(contract_id),
            slot_id=str(slot_id), schema_id=str(schema_id),
            value_ref=f"run-slot:{run_id}:{task_id}:{slot_id}",
            safe_summary=str(safe_summary)[:2000], value=value,
            entity_refs=list(entity_refs or []), provenance_refs=list(provenance_refs or []),
            authority_level=str(authority_level), freshness_time=str(freshness_time),
            completeness_status=str(completeness_status),
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO agent_run_slots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.slot_record_id, record.run_id, record.task_id, record.contract_id,
                    record.slot_id, record.schema_id, record.value_ref, record.safe_summary,
                    json.dumps(record.value, ensure_ascii=False, default=str),
                    json.dumps(record.entity_refs, ensure_ascii=False),
                    json.dumps(record.provenance_refs, ensure_ascii=False),
                    record.authority_level, record.freshness_time,
                    record.completeness_status, record.created_at,
                ),
            )
            connection.commit()
        return record

    def publish_worker_result(self, task: Any, result: Any) -> list[SlotRecord]:
        """Publish only validated, materialized Worker outputs.

        Planned/expected slots are declarations, not data. A failed, blocked,
        partial, or contract-unsatisfied Worker must never create SlotStore rows.
        """

        status = str(
            getattr(getattr(result, "status", None), "value", getattr(result, "status", ""))
            or ""
        )
        completion = dict(getattr(result, "completion", None) or {})
        if status not in {"completed", "proposal_ready"}:
            return []
        if not (
            completion.get("expected_task_completed") is True
            and str(completion.get("completion_status") or "") == "completed"
        ):
            return []

        data = dict(getattr(result, "data", {}) or {})
        values = data.get("slots") if isinstance(data.get("slots"), dict) else {}
        if not values:
            return []

        # Materialized data.slots is the single source of truth. Completion
        # reports and expected outputs are declarations and never manufacture
        # runtime data.
        produced = list(dict.fromkeys(
            str(slot_id)
            for slot_id, value in values.items()
            if str(slot_id) and value is not None
        ))
        if not produced:
            return []

        records: list[SlotRecord] = []
        contract_by_slot: dict[str, str] = {}
        schema_by_slot: dict[str, str] = {}
        for contract in getattr(task, "contracts", []) or []:
            if not isinstance(contract, dict):
                continue
            for output in contract.get("promised_outputs") or []:
                if not isinstance(output, dict):
                    continue
                slot = str(output.get("slot_id") or "")
                contract_by_slot[slot] = str(contract.get("contract_id") or "")
                schema_by_slot[slot] = str(output.get("schema_id") or "")

        allowed = set(contract_by_slot)
        if not allowed:
            return []
        for slot in produced:
            if allowed and slot not in allowed:
                continue
            records.append(self.publish(
                run_id=task.run_id,
                task_id=task.task_id,
                contract_id=contract_by_slot.get(slot, ""),
                slot_id=slot,
                schema_id=schema_by_slot.get(slot, ""),
                value=values[slot],
                safe_summary=str(getattr(result, "summary", ""))[:1000],
                entity_refs=[ref.to_dict() for ref in getattr(result, "focus_refs", [])],
                provenance_refs=[ref.node_id for ref in getattr(result, "evidence_refs", [])],
                freshness_time=str(getattr(task, "as_of_time", "")),
                completeness_status="complete",
            ))
        return records

    def read_bound(self, *, run_id: str, task_id: str, slot_id: str) -> SlotRecord | None:
        """Read the newest slot published by one exact upstream task.

        Worker input projection must follow SlotBinder provenance exactly; it must
        not pick an arbitrary producer when multiple tasks publish the same slot.
        """

        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM agent_run_slots WHERE run_id=? AND task_id=? AND slot_id=? ORDER BY created_at DESC LIMIT 1",
                (str(run_id), str(task_id), str(slot_id)),
            ).fetchone()
        if row is None:
            return None
        return SlotRecord(
            slot_record_id=row["slot_record_id"], run_id=row["run_id"],
            task_id=row["task_id"], contract_id=row["contract_id"],
            slot_id=row["slot_id"], schema_id=row["schema_id"],
            value_ref=row["value_ref"], safe_summary=row["safe_summary"],
            value=json.loads(row["value_json"] or "null"),
            entity_refs=json.loads(row["entity_refs_json"] or "[]"),
            provenance_refs=json.loads(row["provenance_refs_json"] or "[]"),
            authority_level=row["authority_level"], freshness_time=row["freshness_time"],
            completeness_status=row["completeness_status"], created_at=row["created_at"],
        )

    def read(self, *, run_id: str, slot_id: str) -> list[SlotRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM agent_run_slots WHERE run_id=? AND slot_id=? ORDER BY created_at",
                (str(run_id), str(slot_id)),
            ).fetchall()
        result: list[SlotRecord] = []
        for row in rows:
            result.append(SlotRecord(
                slot_record_id=row["slot_record_id"], run_id=row["run_id"],
                task_id=row["task_id"], contract_id=row["contract_id"],
                slot_id=row["slot_id"], schema_id=row["schema_id"],
                value_ref=row["value_ref"], safe_summary=row["safe_summary"],
                value=json.loads(row["value_json"] or "null"),
                entity_refs=json.loads(row["entity_refs_json"] or "[]"),
                provenance_refs=json.loads(row["provenance_refs_json"] or "[]"),
                authority_level=row["authority_level"], freshness_time=row["freshness_time"],
                completeness_status=row["completeness_status"], created_at=row["created_at"],
            ))
        return result
