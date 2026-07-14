from __future__ import annotations

from dataclasses import is_dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any

from agent.communication.message_policy import MessagePolicy
from agent.communication.message_types import AgentMessage, MessageVisibility


REDACTED = "***"


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


class MessageSanitizer:
    def __init__(self, policy: MessagePolicy | None = None) -> None:
        self.policy = policy or MessagePolicy.default()

    def sanitize_for_llm(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="llm")

    def sanitize_for_ui(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="ui")

    def sanitize_for_tool(self, value: Any, *, permission_scope: str = "read") -> dict[str, Any]:
        return self._sanitize(value, target="tool", permission_scope=permission_scope)

    def sanitize_for_audit(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="audit")

    def _sanitize(
        self,
        value: Any,
        *,
        target: str,
        permission_scope: str = "read",
        path: tuple[str, ...] = (),
        current_key: str = "",
    ) -> Any:
        value = _plain(value)
        if isinstance(value, dict):
            return self._sanitize_dict(
                value,
                target=target,
                permission_scope=permission_scope,
                path=path,
            )
        if isinstance(value, list):
            return [
                self._sanitize(
                    item,
                    target=target,
                    permission_scope=permission_scope,
                    path=path,
                    current_key=current_key,
                )
                for item in value
            ]
        if isinstance(value, str):
            visibility = self.policy.classify_field(current_key, value=value, path=path)
            if visibility == MessageVisibility.SECRET:
                return REDACTED if target == "audit" else ""
            if target in {"llm", "ui"} and self._looks_like_internal_stack(value):
                return ""
            if target in {"llm", "ui"} and self._looks_like_local_path(value):
                return ""
            return value
        return value

    def _sanitize_dict(
        self,
        value: dict[str, Any],
        *,
        target: str,
        permission_scope: str,
        path: tuple[str, ...],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            visibility = self.policy.classify_field(key_text, value=item, path=path)
            if visibility == MessageVisibility.SECRET:
                if target == "audit":
                    result[key_text] = REDACTED
                continue
            if target == "audit" and visibility == MessageVisibility.SYSTEM_ONLY:
                result[key_text] = REDACTED
                continue
            if not self.policy.can_deliver(visibility, target, permission_scope=permission_scope):
                if target == "audit":
                    result[key_text] = self._sanitize(
                        item,
                        target=target,
                        permission_scope=permission_scope,
                        path=(*path, key_text),
                        current_key=key_text,
                    )
                elif visibility == MessageVisibility.TOOL_ONLY and self._has_refs(item):
                    result[f"{key_text}_summary"] = self._summarize_large_object(item)
                continue
            result[key_text] = self._sanitize(
                item,
                target=target,
                permission_scope=permission_scope,
                path=(*path, key_text),
                current_key=key_text,
            )
        return result

    @staticmethod
    def _has_refs(value: Any) -> bool:
        if isinstance(value, dict):
            return any(str(key).endswith("_id") or str(key).endswith("_refs") for key in value.keys())
        if isinstance(value, list):
            return bool(value) and all(isinstance(item, dict) for item in value[:5])
        return False

    @staticmethod
    def _summarize_large_object(value: Any) -> dict[str, Any]:
        if isinstance(value, list):
            refs = []
            for item in value[:20]:
                if isinstance(item, dict):
                    ref = {
                        key: item.get(key)
                        for key in ("artifact_id", "chunk_id", "source_id", "stock_code", "tool_call_id")
                        if item.get(key)
                    }
                    if ref:
                        refs.append(ref)
            return {"count": len(value), "refs": refs[:20]}
        if isinstance(value, dict):
            refs = {
                key: value.get(key)
                for key in ("artifact_id", "chunk_id", "source_id", "tool_call_id")
                if value.get(key)
            }
            return {"keys": sorted(str(key) for key in value.keys())[:20], "refs": refs}
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
        return ":\\" in text or lowered.startswith(("c:/", "d:/", "file://")) or "\\users\\" in lowered


def sanitize_message(message: AgentMessage, *, target: str = "llm") -> dict[str, Any]:
    sanitizer = MessageSanitizer()
    if target == "ui":
        return sanitizer.sanitize_for_ui(message)
    if target == "tool":
        return sanitizer.sanitize_for_tool(message)
    if target == "audit":
        return sanitizer.sanitize_for_audit(message)
    return sanitizer.sanitize_for_llm(message)
