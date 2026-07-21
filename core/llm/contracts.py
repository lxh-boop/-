"""Provider-neutral contracts for model execution."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping


class LLMError(RuntimeError):
    """Base exception for the unified LLM boundary."""


class LLMConfigurationError(LLMError):
    """Raised when a profile cannot be executed safely."""


class LLMProviderError(LLMError):
    """Raised when the selected provider fails."""


class LLMResponseError(LLMError):
    """Raised when a provider response violates the text contract."""


class LLMJSONError(LLMResponseError):
    """Raised after the single permitted JSON/schema repair also fails."""


@dataclass(frozen=True)
class LLMResponse:
    """The only response shape exposed by adapters.

    Provider SDK response objects are deliberately not retained here.
    """

    content: str
    provider_id: str
    model_name: str
    profile_id: str
    config_hash: str
    usage: Mapping[str, int] = field(default_factory=dict)
    provider_request_id: str = ""


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object without accepting trailing prose as schema data."""

    raw = str(text or "").strip()
    if not raw:
        raise LLMJSONError("LLM returned empty JSON output.")
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    if start < 0:
        raise LLMJSONError("No JSON object found in LLM output.")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw)):
        char = raw[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise LLMJSONError(f"Invalid JSON returned by LLM: {exc}") from exc
                if not isinstance(parsed, dict):
                    raise LLMJSONError("LLM output is not a JSON object.")
                return parsed
    raise LLMJSONError("Incomplete JSON object returned by LLM.")


__all__ = [
    "LLMConfigurationError",
    "LLMError",
    "LLMJSONError",
    "LLMProviderError",
    "LLMResponse",
    "LLMResponseError",
    "extract_json_object",
]
