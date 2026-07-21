from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent.memory.memory_context_bridge import memory_store_path
from agent.memory.memory_manager import MemoryManager
from agent.memory.memory_types import MemoryRecord, MemoryScope, MemoryStatus, MemoryType


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return bool(row)


def _rows(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]


def _json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    data = {key: _json_value(value) for key, value in row.items()}
    metadata = data.get("metadata") or data.get("metadata_json") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    data["metadata"] = metadata
    return data


def _summary_record(row: dict[str, Any]) -> MemoryRecord:
    content = str(row.get("summary") or row.get("content") or row.get("summary_text") or "")
    return MemoryRecord(
        user_id=str(row.get("user_id") or "default_user"),
        conversation_id=str(row.get("conversation_id") or ""),
        source_type="conversation_summary_migration",
        source_id=str(row.get("summary_id") or row.get("conversation_id") or ""),
        memory_type=MemoryType.EPISODIC,
        memory_subtype="conversation_summary",
        scope=MemoryScope.CONVERSATION,
        status=MemoryStatus.ACTIVE,
        content=content,
        summary=content[:600],
        importance=0.45,
        confidence=0.7,
        created_at=str(row.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or row.get("created_at") or ""),
        metadata={"migrated_from": "conversation_summaries"},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy memory tables to Memory V2.")
    parser.add_argument("--legacy-db", required=True)
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--apply", action="store_true", help="Write records. Default is dry-run.")
    args = parser.parse_args()

    legacy_db = Path(args.legacy_db)
    if not legacy_db.exists():
        raise SystemExit(f"Legacy database not found: {legacy_db}")

    with sqlite3.connect(legacy_db) as conn:
        memory_rows = [_normalise_row(row) for row in _rows(conn, "memory_items")]
        summary_rows = [_normalise_row(row) for row in _rows(conn, "conversation_summaries")]

    records: list[MemoryRecord] = []
    rejected: list[dict[str, str]] = []
    skipped_working = 0
    for row in memory_rows:
        try:
            record = MemoryRecord.from_dict(row)
            record.metadata = {**dict(record.metadata or {}), "migrated_from": "memory_items"}
            if record.memory_type == MemoryType.WORKING:
                skipped_working += 1
                continue
            records.append(record)
        except Exception as exc:
            rejected.append({"source": "memory_items", "id": str(row.get("memory_id") or ""), "error": type(exc).__name__})
    for row in summary_rows:
        try:
            if str(row.get("summary") or row.get("content") or row.get("summary_text") or "").strip():
                records.append(_summary_record(row))
        except Exception as exc:
            rejected.append({"source": "conversation_summaries", "id": str(row.get("summary_id") or ""), "error": type(exc).__name__})

    written = 0
    if args.apply:
        manager = MemoryManager(db_path=memory_store_path(args.output_dir))
        for record in records:
            if record.status == MemoryStatus.CANDIDATE:
                manager.store.upsert(record)
            else:
                manager.remember(record, long_term=True)
            written += 1

    report = {
        "mode": "apply" if args.apply else "dry_run",
        "legacy_memory_count": len(memory_rows),
        "legacy_summary_count": len(summary_rows),
        "convertible_count": len(records),
        "skipped_legacy_working_count": skipped_working,
        "written_count": written,
        "rejected_count": len(rejected),
        "rejected": rejected[:100],
        "target_store": str(memory_store_path(args.output_dir)),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not rejected else 2


if __name__ == "__main__":
    raise SystemExit(main())
