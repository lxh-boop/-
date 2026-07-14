from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any

from .observe_policy import ObservePolicy
from .observation_types import ObservationEvent, ObservationVisibility


REDACTED = "***"
SECRET_TEXT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|confirmation[_-]?token|llm[_-]?api[_-]?key|password|secret|tushare[_-]?token|token)\b\s*(?:[:=]|\s+)\s*[^,\s;，；]+"
)


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


class ObserveSanitizer:
    def __init__(self, policy: ObservePolicy | None = None) -> None:
        self.policy = policy or ObservePolicy.default()

    def sanitize_for_llm(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="llm")

    def sanitize_for_ui(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="ui")

    def sanitize_for_context(self, value: Any) -> dict[str, Any]:
        safe = self._sanitize(value, target="context")
        return self._context_projection(safe)

    def sanitize_for_audit(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="audit")

    def _sanitize(
        self,
        value: Any,
        *,
        target: str,
        path: tuple[str, ...] = (),
        current_key: str = "",
        permission_scope: str = "read",
    ) -> Any:
        value = _plain(value)
        if isinstance(value, dict):
            return self._sanitize_dict(value, target=target, path=path, permission_scope=permission_scope)
        if isinstance(value, list):
            return [
                self._sanitize(
                    item,
                    target=target,
                    path=path,
                    current_key=current_key,
                    permission_scope=permission_scope,
                )
                for item in value
            ]
        if isinstance(value, str):
            visibility = self.policy.classify_field(current_key, value=value, path=path)
            if visibility == ObservationVisibility.SECRET:
                return REDACTED if target == "audit" else ""
            value = self._redact_text(value)
            if target in {"llm", "ui", "context"} and self._looks_like_internal_stack(value):
                return ""
            if target in {"llm", "ui", "context"} and self._looks_like_local_path(value):
                return ""
            return value
        return value

    def _sanitize_dict(
        self,
        value: dict[str, Any],
        *,
        target: str,
        path: tuple[str, ...],
        permission_scope: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            visibility = self.policy.classify_field(key_text, value=item, path=path)
            if visibility == ObservationVisibility.SECRET:
                if target == "audit":
                    result[key_text] = REDACTED
                continue
            if target == "audit" and visibility in {ObservationVisibility.SYSTEM_ONLY, ObservationVisibility.AUDIT_ONLY}:
                result[key_text] = REDACTED if visibility == ObservationVisibility.SYSTEM_ONLY else self._sanitize(
                    item,
                    target=target,
                    path=(*path, key_text),
                    current_key=key_text,
                    permission_scope=permission_scope,
                )
                continue
            if not self.policy.can_deliver(visibility, target, permission_scope=permission_scope):
                if visibility == ObservationVisibility.TOOL_ONLY and target in {"llm", "ui", "context"}:
                    result[self._safe_summary_key(key_text)] = self._summarize_large_object(item)
                elif target == "audit":
                    result[key_text] = self._sanitize(
                        item,
                        target=target,
                        path=(*path, key_text),
                        current_key=key_text,
                        permission_scope=permission_scope,
                    )
                continue
            result[key_text] = self._sanitize(
                item,
                target=target,
                path=(*path, key_text),
                current_key=key_text,
                permission_scope=permission_scope,
            )
        return result

    def _context_projection(self, value: dict[str, Any]) -> dict[str, Any]:
        keys = {
            "observation_id",
            "observation_type",
            "status",
            "severity",
            "summary",
            "context_refs",
            "artifact_refs",
            "message_refs",
            "memory_refs",
            "approval_refs",
            "tool_call_refs",
            "source_refs",
            "error",
            "warnings",
        }
        return {key: value.get(key) for key in keys if key in value}

    @staticmethod
    def _summarize_large_object(value: Any) -> dict[str, Any]:
        if isinstance(value, list):
            refs = []
            for item in value[:20]:
                if isinstance(item, dict):
                    ref = {
                        key: item.get(key)
                        for key in ("artifact_id", "chunk_id", "source_id", "stock_code", "tool_call_id", "memory_id")
                        if item.get(key)
                    }
                    if ref:
                        refs.append(ref)
            return {"count": len(value), "refs": refs[:20]}
        if isinstance(value, dict):
            safe_keys = [
                str(key)
                for key in value.keys()
                if str(key).lower() not in {"api_key", "confirmation_token", "llm_api_key", "password", "secret", "tushare_token", "token"}
            ]
            refs = {
                key: value.get(key)
                for key in ("artifact_id", "chunk_id", "source_id", "tool_call_id", "memory_id")
                if value.get(key)
            }
            return {"keys": sorted(safe_keys)[:20], "refs": refs}
        return {"type": type(value).__name__}

    @staticmethod
    def _safe_summary_key(key: str) -> str:
        lowered = str(key or "").lower()
        if "evidence" in lowered:
            return "evidence_summary"
        if "position" in lowered:
            return "positions_summary"
        if "payload" in lowered:
            return "tool_payload_summary"
        if "result" in lowered:
            return "tool_result_summary"
        return "object_summary"

    @staticmethod
    def _redact_text(text: str) -> str:
        return SECRET_TEXT_RE.sub("[redacted-secret]", str(text or ""))

    @staticmethod
    def _looks_like_internal_stack(text: str) -> bool:
        lowered = str(text or "").lower()
        return "traceback (most recent call last)" in lowered or ("file \"" in lowered and "line " in lowered)

    @staticmethod
    def _looks_like_local_path(text: str) -> bool:
        lowered = str(text or "").lower()
        if "://" in lowered and not lowered.startswith("file://"):
            return False
        return ":\\" in str(text) or lowered.startswith(("c:/", "d:/", "file://")) or "\\users\\" in lowered


def sanitize_observation(observation: ObservationEvent | dict[str, Any], *, target: str = "llm") -> dict[str, Any]:
    sanitizer = ObserveSanitizer()
    if target == "ui":
        return sanitizer.sanitize_for_ui(observation)
    if target == "context":
        return sanitizer.sanitize_for_context(observation)
    if target == "audit":
        return sanitizer.sanitize_for_audit(observation)
    return sanitizer.sanitize_for_llm(observation)
