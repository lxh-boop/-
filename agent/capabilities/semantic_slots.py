"""Generic semantic-slot helpers for Worker-to-Worker runtime data flow.

Slot ids are runtime semantic keys, not a closed business enum. Capability
boundaries restrict semantic *families* with wildcard patterns; concrete tasks
may introduce new keys without changing Runtime code. Required field paths are
validated and projected deterministically before a Worker sees the value.
"""

from __future__ import annotations

from copy import deepcopy
from fnmatch import fnmatchcase
import json
import re
from typing import Any, Iterable


_SLOT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class SemanticSlotError(ValueError):
    def __init__(self, code: str, *, slot_id: str = "", detail: str = "") -> None:
        self.code = str(code or "semantic_slot_error")
        self.slot_id = str(slot_id or "")
        self.detail = str(detail or "")
        message = self.code
        if self.slot_id:
            message += f":{self.slot_id}"
        if self.detail:
            message += f":{self.detail}"
        super().__init__(message)


def normalize_slot_id(value: Any) -> str:
    return str(value or "").strip().lower()


def validate_slot_id(value: Any) -> str:
    slot_id = normalize_slot_id(value)
    if not slot_id or not _SLOT_ID_RE.fullmatch(slot_id):
        raise SemanticSlotError("invalid_semantic_slot_id", slot_id=slot_id)
    return slot_id


def slot_matches_patterns(slot_id: str, patterns: Iterable[str]) -> bool:
    key = normalize_slot_id(slot_id)
    wanted = [str(item or "").strip().lower() for item in patterns if str(item or "").strip()]
    return bool(key and any(fnmatchcase(key, pattern) for pattern in wanted))


def _segments(path: str) -> list[tuple[str, bool]]:
    text = str(path or "").strip()
    if text.startswith("$."):
        text = text[2:]
    elif text == "$":
        return []
    result: list[tuple[str, bool]] = []
    for raw in [item for item in text.split(".") if item]:
        if raw.endswith("[*]"):
            result.append((raw[:-3], True))
        else:
            result.append((raw, False))
    return result


def path_exists(value: Any, path: str) -> bool:
    segments = _segments(path)
    if not segments:
        return value is not None

    def exists(node: Any, index: int) -> bool:
        key, wildcard = segments[index]
        if not isinstance(node, dict) or key not in node:
            return False
        child = node[key]
        is_last = index == len(segments) - 1

        if wildcard:
            if not isinstance(child, list):
                return False
            # An empty collection is structurally valid. Business-empty is a
            # separate semantic state and must not be reclassified as a missing
            # field contract failure.
            if not child:
                return True
            if is_last:
                return True
            # For a non-empty record collection every item must satisfy the
            # required tail path; one valid row must not hide malformed peers.
            return all(exists(item, index + 1) for item in child)

        if is_last:
            return child is not None
        return exists(child, index + 1)

    return exists(value, 0)


def missing_required_paths(value: Any, required_paths: Iterable[str]) -> list[str]:
    return [
        str(path)
        for path in required_paths
        if str(path or "").strip() and not path_exists(value, str(path))
    ]


def _merge_projected(target: Any, source: Any, segments: list[tuple[str, bool]]) -> Any:
    if not segments:
        return deepcopy(source)
    if not isinstance(source, dict):
        return target
    if not isinstance(target, dict):
        target = {}

    key, wildcard = segments[0]
    if key not in source:
        return target
    child = source[key]
    tail = segments[1:]

    if wildcard:
        if not isinstance(child, list):
            return target
        existing = target.get(key)
        if not isinstance(existing, list):
            existing = [{} for _ in child]
        if len(existing) < len(child):
            existing.extend({} for _ in range(len(child) - len(existing)))
        projected_items: list[Any] = []
        for index, item in enumerate(child):
            base = existing[index] if index < len(existing) else {}
            projected_items.append(_merge_projected(base, item, tail))
        target[key] = projected_items
        return target

    if not tail:
        target[key] = deepcopy(child)
        return target

    target[key] = _merge_projected(target.get(key, {}), child, tail)
    return target


def project_paths(value: Any, paths: Iterable[str]) -> Any:
    selected = [str(item).strip() for item in paths if str(item or "").strip()]
    if not selected:
        return deepcopy(value)
    projected: Any = {}
    for path in selected:
        projected = _merge_projected(projected, value, _segments(path))
    return projected


def estimate_json_chars(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")))
    except Exception:
        return len(str(value))


def estimate_tokens(value: Any) -> int:
    # Cheap deterministic audit estimate. Provider tokenization is intentionally
    # not imported into Runtime projection.
    chars = estimate_json_chars(value)
    return max(1, (chars + 3) // 4) if chars else 0


__all__ = [
    "SemanticSlotError",
    "estimate_json_chars",
    "estimate_tokens",
    "missing_required_paths",
    "normalize_slot_id",
    "path_exists",
    "project_paths",
    "slot_matches_patterns",
    "validate_slot_id",
]
