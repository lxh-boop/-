from __future__ import annotations

import re
from dataclasses import is_dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any

from .memory_policy import MemoryPolicy
from .memory_types import MemoryRecord, MemoryVisibility


REDACTED = "***"
SECRET_TEXT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|confirmation[_-]?token|llm[_-]?api[_-]?key|password|secret|tushare[_-]?token|token)\b\s*(?:[:=]|\s+)\s*[^,\s;，；]+"
)
WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:[\\/][^\s,;，；]+")
UNIX_PRIVATE_PATH_RE = re.compile(r"(?i)(/users/|/home/)[^\s,;，；]+")


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {str(key): _plain(item) for key, item in asdict(value).items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


class MemorySanitizer:
    def __init__(self, policy: MemoryPolicy | None = None, *, max_text_chars: int = 2000) -> None:
        self.policy = policy or MemoryPolicy.default()
        self.max_text_chars = max_text_chars

    def sanitize_for_storage(self, value: Any) -> Any:
        return self._sanitize(value, target="storage")

    def sanitize_for_llm(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="llm")

    def sanitize_for_ui(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="ui")

    def sanitize_for_audit(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="audit")

    def sanitize_record(self, record: MemoryRecord | dict[str, Any]) -> MemoryRecord:
        source = record if isinstance(record, MemoryRecord) else MemoryRecord.from_dict(record)
        data = source.to_dict()
        sanitized = self.sanitize_for_storage(data)
        return MemoryRecord.from_dict(sanitized)

    def _sanitize(
        self,
        value: Any,
        *,
        target: str,
        path: tuple[str, ...] = (),
        current_key: str = "",
    ) -> Any:
        value = _plain(value)
        if isinstance(value, dict):
            return self._sanitize_dict(value, target=target, path=path)
        if isinstance(value, list):
            return [
                self._sanitize(item, target=target, path=path, current_key=current_key)
                for item in value[:100]
            ]
        if isinstance(value, str):
            return self._sanitize_text(value, target=target, current_key=current_key, path=path)
        return value

    def _sanitize_dict(self, value: dict[str, Any], *, target: str, path: tuple[str, ...]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            visibility = self.policy.classify_field(key_text, value=item, path=path)
            if visibility == MemoryVisibility.SECRET:
                if target == "audit":
                    result[key_text] = REDACTED
                continue
            if target in {"storage", "llm", "ui"} and visibility in {
                MemoryVisibility.SYSTEM_ONLY,
                MemoryVisibility.AUDIT_ONLY,
            }:
                continue
            if visibility == MemoryVisibility.TOOL_ONLY:
                summary_key, summary_value = self._summarize_large_object(key_text, item)
                if summary_key:
                    result[summary_key] = summary_value
                continue
            if target in {"llm", "ui"} and not self.policy.can_deliver(visibility, target):
                continue
            result[key_text] = self._sanitize(
                item,
                target=target,
                path=(*path, key_text),
                current_key=key_text,
            )
        return result

    def _sanitize_text(
        self,
        text: str,
        *,
        target: str,
        current_key: str,
        path: tuple[str, ...],
    ) -> str:
        visibility = self.policy.classify_field(current_key, value=text, path=path)
        if visibility == MemoryVisibility.SECRET:
            return REDACTED if target == "audit" else ""
        safe = SECRET_TEXT_RE.sub("[redacted-secret]", str(text or ""))
        if self._looks_like_internal_stack(safe):
            return REDACTED if target == "audit" else ""
        safe = WINDOWS_PATH_RE.sub("[redacted-path]", safe)
        safe = UNIX_PRIVATE_PATH_RE.sub("[redacted-path]", safe)
        safe = re.sub(r"(?i)\bagent_quant\.db\b", "[redacted-db]", safe)
        if target in {"llm", "ui"} and self._looks_like_local_path(safe):
            return ""
        return safe[: self.max_text_chars]

    @staticmethod
    def _summarize_large_object(key: str, value: Any) -> tuple[str, dict[str, Any]]:
        lowered = str(key or "").lower()
        if "position" in lowered:
            return "positions_summary", _summarize_refs(value, ("stock_code", "quantity", "market_value"))
        if "evidence" in lowered:
            return "evidence_summary", _summarize_refs(value, ("artifact_id", "chunk_id", "source_id", "stock_code"))
        if "payload" in lowered or "result" in lowered:
            return "payload_summary", _summarize_refs(value, ("tool_call_id", "artifact_id", "source_id"))
        return "object_summary", _summarize_refs(value, ("artifact_id", "source_id"))

    @staticmethod
    def _looks_like_internal_stack(text: str) -> bool:
        lowered = str(text or "").lower()
        return "traceback (most recent call last)" in lowered or ("file \"" in lowered and "line " in lowered)

    @staticmethod
    def _looks_like_local_path(text: str) -> bool:
        lowered = str(text or "").lower()
        if "://" in lowered and not lowered.startswith("file://"):
            return False
        return ":\\" in text or lowered.startswith(("c:/", "d:/", "file://")) or "\\users\\" in lowered


def _summarize_refs(value: Any, ref_keys: tuple[str, ...]) -> dict[str, Any]:
    if isinstance(value, list):
        refs = []
        for item in value[:20]:
            if isinstance(item, dict):
                ref = {key: item.get(key) for key in ref_keys if item.get(key) is not None}
                if ref:
                    refs.append(ref)
        return {"count": len(value), "refs": refs}
    if isinstance(value, dict):
        refs = {key: value.get(key) for key in ref_keys if value.get(key) is not None}
        return {"keys": sorted(str(key) for key in value.keys())[:20], "refs": refs}
    return {"type": type(value).__name__}
