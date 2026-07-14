from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .memory_policy import MemoryPolicy
from .memory_sanitizer import MemorySanitizer
from .memory_types import MemoryRecord, MemoryStatus, MemoryType


def _now() -> datetime:
    return datetime.now()


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class WorkingMemoryEntry:
    record: MemoryRecord
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at <= (now or _now())


class WorkingMemory:
    def __init__(
        self,
        *,
        default_ttl_seconds: int = 1800,
        policy: MemoryPolicy | None = None,
        sanitizer: MemorySanitizer | None = None,
    ) -> None:
        self.default_ttl_seconds = max(1, int(default_ttl_seconds or 1800))
        self.policy = policy or MemoryPolicy.default()
        self.sanitizer = sanitizer or MemorySanitizer(self.policy)
        self._items: dict[str, WorkingMemoryEntry] = {}

    def put(self, record: MemoryRecord | dict[str, Any], *, ttl_seconds: int | None = None) -> MemoryRecord:
        safe = self.sanitizer.sanitize_record(record)
        if safe.memory_type != MemoryType.WORKING:
            safe.memory_type = MemoryType.WORKING
        safe.status = MemoryStatus.ACTIVE
        self.policy.assert_can_store(safe)
        ttl = max(1, int(ttl_seconds or self.default_ttl_seconds))
        expires_at = _now() + timedelta(seconds=ttl)
        safe.valid_until = expires_at.isoformat(timespec="seconds")
        self._items[safe.memory_id] = WorkingMemoryEntry(record=safe, expires_at=expires_at)
        return safe

    def get(self, memory_id: str, *, user_id: str = "", include_expired: bool = False) -> MemoryRecord | None:
        self.clear_expired()
        entry = self._items.get(str(memory_id or ""))
        if not entry:
            return None
        if user_id and entry.record.user_id != str(user_id):
            return None
        if entry.is_expired() and not include_expired:
            return None
        return entry.record

    def delete(self, memory_id: str, *, user_id: str = "") -> bool:
        record = self.get(memory_id, user_id=user_id, include_expired=True)
        if not record:
            return False
        self._items.pop(record.memory_id, None)
        return True

    def clear_expired(self) -> int:
        now = _now()
        expired = [memory_id for memory_id, entry in self._items.items() if entry.is_expired(now)]
        for memory_id in expired:
            self._items.pop(memory_id, None)
        return len(expired)

    def list_records(
        self,
        *,
        user_id: str = "",
        memory_types: list[MemoryType | str] | None = None,
        include_expired: bool = False,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        if not include_expired:
            self.clear_expired()
        allowed = {MemoryType.from_value(item) for item in (memory_types or [])}
        records: list[MemoryRecord] = []
        for entry in self._items.values():
            if user_id and entry.record.user_id != str(user_id):
                continue
            if allowed and entry.record.memory_type not in allowed:
                continue
            if entry.is_expired() and not include_expired:
                continue
            records.append(entry.record)
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return records[: max(1, int(limit or 100))]

    def search(
        self,
        *,
        user_id: str,
        query: str = "",
        topics: list[str] | None = None,
        stock_codes: list[str] | None = None,
        min_importance: float = 0.0,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        query_text = str(query or "").lower()
        topic_set = {str(item).lower() for item in (topics or [])}
        stock_set = {str(item).split(".")[0].zfill(6) for item in (stock_codes or [])}
        records = []
        for record in self.list_records(user_id=user_id, limit=1000):
            if record.importance < float(min_importance or 0.0):
                continue
            if topic_set and not (topic_set & {item.lower() for item in record.topics}):
                continue
            if stock_set and not (stock_set & set(record.stock_codes)):
                continue
            if query_text:
                haystack = " ".join([record.content, record.summary, " ".join(record.topics), " ".join(record.stock_codes)]).lower()
                if not any(token for token in query_text.split() if token and token in haystack):
                    continue
            records.append(record)
        records.sort(key=lambda item: (item.importance, item.updated_at), reverse=True)
        return records[: max(1, int(limit or 10))]


def is_record_expired(record: MemoryRecord, now: datetime | None = None) -> bool:
    valid_until = _parse_time(record.valid_until)
    return bool(valid_until and valid_until <= (now or _now()))
