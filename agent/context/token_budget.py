from __future__ import annotations

import json
from typing import Any


def estimate_tokens(value: Any) -> int:
    """Small deterministic token estimate used before an LLM call.

    This is intentionally conservative and dependency-free.  It is used only
    for budgeting and never for billing or model accounting.
    """

    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if not value:
        return 0
    ascii_count = sum(1 for char in value if ord(char) < 128)
    non_ascii_count = len(value) - ascii_count
    return max(1, int(ascii_count / 4) + int(non_ascii_count / 2))


def truncate_text_to_tokens(value: Any, max_tokens: int) -> str:
    text = str(value or "")
    budget = max(1, int(max_tokens or 1))
    if estimate_tokens(text) <= budget:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= budget:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + "…"


__all__ = ["estimate_tokens", "truncate_text_to_tokens"]
