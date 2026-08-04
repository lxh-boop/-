"""Prompt-only serialization helpers.

These helpers never mutate runtime schemas, contracts, tasks, results, or
validators. They only create smaller read-only views for LLM request payloads.
"""

from __future__ import annotations

import json
from typing import Any


_SCHEMA_ANNOTATION_KEYS = {
    "$comment",
    "deprecated",
    "description",
    "example",
    "examples",
    "readOnly",
    "title",
    "writeOnly",
}


def schema_for_prompt(value: Any) -> Any:
    """Remove non-validating JSON-Schema annotations from a copied value.

    Structural validation keywords, required fields, enums, bounds, defaults,
    and additionalProperties are preserved exactly. The original object is not
    modified and remains the only object used by runtime validation.
    """

    if isinstance(value, dict):
        return {
            str(key): schema_for_prompt(item)
            for key, item in value.items()
            if str(key) not in _SCHEMA_ANNOTATION_KEYS
        }
    if isinstance(value, list):
        return [schema_for_prompt(item) for item in value]
    if isinstance(value, tuple):
        return [schema_for_prompt(item) for item in value]
    return value


def catalog_for_prompt(value: Any, *, parent_key: str = "") -> Any:
    """Create a semantics-preserving prompt view of capability catalogs.

    Only nested fields explicitly named as schemas are annotation-stripped.
    Worker descriptions, examples, criteria, side-effect boundaries, and all
    capability semantics remain unchanged.
    """

    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if "schema" in key_text.lower():
                result[key_text] = schema_for_prompt(item)
            else:
                result[key_text] = catalog_for_prompt(item, parent_key=key_text)
        return result
    if isinstance(value, list):
        return [catalog_for_prompt(item, parent_key=parent_key) for item in value]
    if isinstance(value, tuple):
        return [catalog_for_prompt(item, parent_key=parent_key) for item in value]
    return value


def compact_json_dumps(value: Any) -> str:
    """Serialize without optional whitespace while preserving all values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


__all__ = ["catalog_for_prompt", "compact_json_dumps", "schema_for_prompt"]
