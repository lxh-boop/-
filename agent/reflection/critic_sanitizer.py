from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
import re
from typing import Any

from .critic_policy import CriticPolicy, CriticVisibility
from .critic_types import CriticResult


REDACTED = "***"
SECRET_TEXT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|confirmation[_-]?token|llm[_-]?api[_-]?key|password|secret|tushare[_-]?token|token)\b\s*(?:[:=]|\s+)\s*[^,\s;锛岋紱]+"
)
WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:[\\/][^\s,;锛岋紱]+")
UNIX_PRIVATE_PATH_RE = re.compile(r"(?i)(/users/|/home/)[^\s,;锛岋紱]+")


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


class CriticSanitizer:
    def __init__(self, policy: CriticPolicy | None = None, *, max_text_chars: int = 2000) -> None:
        self.policy = policy or CriticPolicy.default()
        self.max_text_chars = int(max_text_chars or 2000)

    def sanitize_for_llm(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="llm")

    def sanitize_for_ui(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="ui")

    def sanitize_for_audit(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="audit")

    def sanitize_for_context(self, value: Any) -> dict[str, Any]:
        safe = self._sanitize(value, target="context")
        if isinstance(safe, dict):
            return self._context_projection(safe)
        return safe

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
                for item in value[:100]
            ]
        if isinstance(value, str):
            return self._sanitize_text(value, target=target, current_key=current_key, path=path)
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
            if visibility == CriticVisibility.SECRET:
                if target == "audit":
                    result[key_text] = REDACTED
                continue
            if target == "audit" and visibility in {CriticVisibility.SYSTEM_ONLY, CriticVisibility.AUDIT_ONLY}:
                result[key_text] = REDACTED if visibility == CriticVisibility.SYSTEM_ONLY else self._sanitize(
                    item,
                    target=target,
                    path=(*path, key_text),
                    current_key=key_text,
                    permission_scope=permission_scope,
                )
                continue
            if not self.policy.can_deliver(visibility, target, permission_scope=permission_scope):
                if visibility == CriticVisibility.TOOL_ONLY and target in {"llm", "ui", "context"}:
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

    def _sanitize_text(
        self,
        text: str,
        *,
        target: str,
        current_key: str,
        path: tuple[str, ...],
    ) -> str:
        visibility = self.policy.classify_field(current_key, value=text, path=path)
        if visibility == CriticVisibility.SECRET:
            return REDACTED if target == "audit" else ""
        safe = SECRET_TEXT_RE.sub("[redacted-secret]", str(text or ""))
        safe = WINDOWS_PATH_RE.sub("[redacted-path]", safe)
        safe = UNIX_PRIVATE_PATH_RE.sub("[redacted-path]", safe)
        safe = re.sub(r"(?i)\bagent_quant\.db\b", "[redacted-db]", safe)
        if self._looks_like_internal_stack(safe):
            return REDACTED if target == "audit" else ""
        if target in {"llm", "ui", "context"} and self._looks_like_local_path(safe):
            return ""
        return safe[: self.max_text_chars]

    @staticmethod
    def _context_projection(value: dict[str, Any]) -> dict[str, Any]:
        keys = {
            "critic_id",
            "conversation_id",
            "run_id",
            "task_id",
            "target_type",
            "target_ref",
            "target_summary",
            "verdict",
            "action",
            "severity",
            "score",
            "issues",
            "evidence_refs",
            "observation_refs",
            "replan_refs",
            "message_refs",
            "memory_refs",
            "approval_refs",
            "revision_instruction",
            "replan_hint",
            "handoff_hint",
            "requires_user_confirmation",
            "created_at",
        }
        return {key: value.get(key) for key in keys if key in value}

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

    def _summarize_large_object(self, value: Any) -> dict[str, Any]:
        if isinstance(value, list):
            refs = []
            for item in value[:20]:
                if isinstance(item, dict):
                    ref = {
                        key: item.get(key)
                        for key in ("artifact_id", "chunk_id", "source_id", "stock_code", "tool_call_id", "memory_id")
                        if item.get(key) is not None
                    }
                    if ref:
                        refs.append(ref)
            return {"count": len(value), "refs": refs}
        if isinstance(value, dict):
            safe_keys = [
                str(key)
                for key in value.keys()
                if not self.policy.requires_redaction(str(key), value=value.get(key))
            ]
            refs = {
                key: value.get(key)
                for key in ("artifact_id", "chunk_id", "source_id", "tool_call_id", "memory_id")
                if value.get(key) is not None
            }
            return {"keys": sorted(safe_keys)[:20], "refs": refs}
        return {"type": type(value).__name__}

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


def sanitize_critic_result(result: CriticResult | dict[str, Any], *, target: str = "llm") -> dict[str, Any]:
    sanitizer = CriticSanitizer()
    if target == "ui":
        return sanitizer.sanitize_for_ui(result)
    if target == "context":
        return sanitizer.sanitize_for_context(result)
    if target == "audit":
        return sanitizer.sanitize_for_audit(result)
    return sanitizer.sanitize_for_llm(result)
