"""Node-scoped minimum context projection with deterministic token budgeting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContextProjectionRequest:
    node_type: str
    required_slots: list[str] = field(default_factory=list)
    allowed_context_keys: list[str] = field(default_factory=list)
    token_budget: int = 2400


class ContextProjector:
    def project(self, source: dict[str, Any], request: ContextProjectionRequest) -> dict[str, Any]:
        allowed = set(request.allowed_context_keys) | set(request.required_slots)
        result = {key: value for key, value in source.items() if key in allowed}
        # Required identifiers and GraphRefs are never silently dropped.
        for key in request.required_slots:
            if key in source:
                result[key] = source[key]
        # Compact deterministic character budget; the LLM token counter remains
        # the authoritative runtime limiter in core.llm.
        maximum_chars = max(1000, int(request.token_budget) * 4)
        while len(str(result)) > maximum_chars:
            removable = [key for key in result if key not in request.required_slots]
            if not removable:
                break
            result.pop(removable[-1], None)
        return result
