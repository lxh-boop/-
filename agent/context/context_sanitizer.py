from __future__ import annotations

from dataclasses import is_dataclass, asdict
from pathlib import Path
from typing import Any

from agent.context.context_policy import ContextPolicy, ContextVisibility


REDACTED = "***"


def _plain(value: Any) -> Any:
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


class ContextSanitizer:
    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self.policy = policy or ContextPolicy.default()

    def sanitize_for_llm(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="llm")

    def sanitize_for_tool(self, value: Any, *, permission_scope: str = "read") -> dict[str, Any]:
        return self._sanitize(value, target="tool", permission_scope=permission_scope)

    def sanitize_for_ui(self, value: Any) -> dict[str, Any]:
        return self._sanitize(value, target="ui")

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
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                visibility = self.policy.visibility_for(key_text, value=item, path=path)
                if visibility == ContextVisibility.SECRET:
                    if target == "audit":
                        result[key_text] = REDACTED
                    continue
                if not self.policy.is_visible_for(
                    key_text,
                    target,
                    value=item,
                    path=path,
                    permission_scope=permission_scope,
                ):
                    if target == "audit":
                        result[key_text] = self._sanitize(
                            item,
                            target=target,
                            permission_scope=permission_scope,
                            path=(*path, key_text),
                            current_key=key_text,
                        )
                    continue
                result[key_text] = self._sanitize(
                    item,
                    target=target,
                    permission_scope=permission_scope,
                    path=(*path, key_text),
                    current_key=key_text,
                )
            return result
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
            if self.policy.visibility_for(current_key, value=value, path=path) == ContextVisibility.SECRET:
                return REDACTED if target == "audit" else ""
            if target in {"llm", "ui"} and self._looks_like_internal_stack(value):
                return ""
            return value
        return value

    @staticmethod
    def _looks_like_internal_stack(text: str) -> bool:
        lowered = str(text or "").lower()
        return "traceback (most recent call last)" in lowered or "file \"" in lowered and "line " in lowered
