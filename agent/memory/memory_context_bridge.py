from __future__ import annotations

from pathlib import Path
from typing import Any

from .memory_manager import MemoryManager
from .memory_sanitizer import MemorySanitizer
from .memory_store import DEFAULT_MEMORY_STORE_PATH, SQLiteMemoryStore


def memory_store_path(output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "memory" / DEFAULT_MEMORY_STORE_PATH.name


def get_memory_manager_for_output(output_dir: str | Path = "outputs") -> MemoryManager:
    return MemoryManager(db_path=memory_store_path(output_dir))


def build_memory_context_view(
    *,
    user_id: str,
    query: str = "",
    output_dir: str | Path = "outputs",
    limit: int = 6,
) -> dict[str, Any]:
    manager = get_memory_manager_for_output(output_dir)
    view = manager.retrieve_for_context(
        user_id=user_id,
        query=query,
        limit=limit,
        include_working=False,
        include_long_term=True,
    )
    items = list(view.get("items") or [])
    memory_refs = [
        str((item.get("memory") or {}).get("memory_id") or "")
        for item in items
        if (item.get("memory") or {}).get("memory_id")
    ]
    return {
        "memory_refs": memory_refs,
        "item_count": len(items),
        "items": items,
        "policy": view.get("policy") or {},
    }


def build_memory_store_health_summary(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    try:
        path = memory_store_path(output_dir)
        store = SQLiteMemoryStore(path)
        total_count = store.count()
        user_count = store.count(user_id=user_id)
        latest = store.list_records(user_id=user_id, limit=5)
        return {
            "status": "ok",
            "store": "outputs/memory/memory_store.sqlite",
            "exists": path.exists(),
            "total_count": total_count,
            "user_count": user_count,
            "latest_memory_count": len(latest),
            "latest_memory_types": sorted({record.memory_type.value for record in latest}),
            "secret_safe": True,
            "write_permission": "none",
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "store": "outputs/memory/memory_store.sqlite",
            "exists": False,
            "total_count": 0,
            "user_count": 0,
            "latest_memory_count": 0,
            "latest_memory_types": [],
            "secret_safe": True,
            "write_permission": "none",
            "error": type(exc).__name__,
        }


def build_memory_safe_summary(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
) -> str:
    health = build_memory_store_health_summary(user_id=user_id, output_dir=output_dir)
    return (
        "Memory safe summary: "
        f"status={health.get('status')} | "
        f"user_records={health.get('user_count')} | "
        f"latest={health.get('latest_memory_count')} | "
        f"write_permission={health.get('write_permission')} | "
        f"secret_safe={health.get('secret_safe')}"
    )


def list_memory_records_safe_page(
    *,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    limit: int = 5,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a small UI-safe page of memory records without raw internals."""
    try:
        store = SQLiteMemoryStore(memory_store_path(output_dir))
        total = store.count(user_id=user_id)
        start = max(0, int(offset or 0))
        page_size = max(1, min(50, int(limit or 5)))
        records = store.list_records(user_id=user_id, limit=start + page_size)
        sanitizer = MemorySanitizer(max_text_chars=300)
        rows = []
        for record in records[start : start + page_size]:
            safe = sanitizer.sanitize_for_ui(record)
            rows.append(
                {
                    "memory_id": str(safe.get("memory_id") or "")[:96],
                    "memory_type": str(safe.get("memory_type") or "")[:64],
                    "memory_subtype": str(safe.get("memory_subtype") or "")[:64],
                    "scope": str(safe.get("scope") or "")[:64],
                    "summary": str(safe.get("summary") or safe.get("content") or "")[:220],
                    "topics": list(safe.get("topics") or [])[:8],
                    "stock_codes": list(safe.get("stock_codes") or [])[:8],
                    "importance": safe.get("importance"),
                    "confidence": safe.get("confidence"),
                    "updated_at": str(safe.get("updated_at") or "")[:19],
                }
            )
        return {
            "status": "ok",
            "total_count": total,
            "offset": start,
            "limit": page_size,
            "records": rows,
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
            },
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "total_count": 0,
            "offset": max(0, int(offset or 0)),
            "limit": max(1, min(50, int(limit or 5))),
            "records": [],
            "error": type(exc).__name__,
            "safety": {
                "secrets_redacted": True,
                "raw_paths_hidden": True,
                "raw_payload_hidden": True,
            },
        }


def extract_memory_candidates_from_message_trace(
    messages: list[dict[str, Any]],
    *,
    user_id: str,
    output_dir: str | Path = "outputs",
) -> list[dict[str, Any]]:
    manager = get_memory_manager_for_output(output_dir)
    candidates = []
    for message in messages:
        candidates.extend(manager.remember_candidate(message, user_id=user_id, source_type="message"))
    return [candidate.to_dict() for candidate in candidates]


def extract_memory_candidates_from_artifact(
    artifact: dict[str, Any],
    *,
    user_id: str,
    output_dir: str | Path = "outputs",
) -> list[dict[str, Any]]:
    manager = get_memory_manager_for_output(output_dir)
    candidates = manager.extractor.extract({"user_id": user_id, **dict(artifact or {})}, source_type="artifact", user_id=user_id)
    return [candidate.to_dict() for candidate in candidates]
