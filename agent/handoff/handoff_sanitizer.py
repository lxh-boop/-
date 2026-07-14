from __future__ import annotations

from dataclasses import is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .handoff_policy import HandoffPolicy


REDACTED = "[REDACTED]"

PRIVATE_REASONING_KEYS = {
    "chain_of_thought",
    "cot",
    "hidden_reasoning",
    "internal_reasoning",
    "private_reasoning",
    "reasoning_trace",
    "thought",
    "thoughts",
}


class HandoffSanitizer:
    def __init__(self, policy: HandoffPolicy | None = None) -> None:
        self.policy = policy or HandoffPolicy.default()

    def sanitize_for_llm(self, value: Any) -> Any:
        return self._sanitize(value, target="llm", path=())

    def sanitize_for_ui(self, value: Any) -> Any:
        return self._sanitize(value, target="ui", path=())

    def sanitize_for_audit(self, value: Any) -> Any:
        return self._sanitize(value, target="audit", path=())

    def sanitize_request(self, value: Any, *, target: str = "llm") -> dict[str, Any]:
        sanitized = self._sanitize(value, target=target, path=())
        return sanitized if isinstance(sanitized, dict) else {}

    def sanitize_result(self, value: Any, *, target: str = "llm") -> dict[str, Any]:
        sanitized = self._sanitize(value, target=target, path=())
        return sanitized if isinstance(sanitized, dict) else {}

    def _sanitize(self, value: Any, *, target: str, path: tuple[str, ...]) -> Any:
        if hasattr(value, "to_dict") and callable(value.to_dict):
            return self._sanitize(value.to_dict(), target=target, path=path)
        if is_dataclass(value):
            data = {str(key): item for key, item in value.__dict__.items()}
            return self._sanitize(data, target=target, path=path)
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Path):
            return REDACTED
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                lowered = key_text.lower()
                if lowered in PRIVATE_REASONING_KEYS:
                    result[key_text] = REDACTED
                    continue
                if target in {"llm", "ui"} and not self.policy.can_show_to_llm(key_text, item, path):
                    result[key_text] = REDACTED
                    continue
                result[key_text] = self._sanitize(item, target=target, path=(*path, lowered))
            return result
        if isinstance(value, list):
            return [self._sanitize(item, target=target, path=path) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize(item, target=target, path=path) for item in value]
        if isinstance(value, str):
            return self._sanitize_text(value, target=target)
        return value

    @staticmethod
    def _sanitize_text(value: str, *, target: str) -> str:
        if target not in {"llm", "ui"}:
            return value
        text = str(value or "")
        lowered = text.lower()
        if "confirmation_token" in lowered or "traceback" in lowered or "api_key" in lowered:
            return REDACTED
        if ":\\" in text or ":/" in text or "appdata\\local" in lowered:
            return REDACTED
        return text


def sanitize_handoff(value: Any, *, target: str = "llm") -> Any:
    sanitizer = HandoffSanitizer()
    if target == "ui":
        return sanitizer.sanitize_for_ui(value)
    if target == "audit":
        return sanitizer.sanitize_for_audit(value)
    return sanitizer.sanitize_for_llm(value)
