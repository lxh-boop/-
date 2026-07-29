"""Generic contracts and schema validation for coordinator-visible Workers.

This module deliberately knows nothing about user-query business semantics.  It
validates only declared Worker contracts: JSON shape, required inputs, declared
outputs, dependency bindings, and side-effect metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WorkerContractViolation(ValueError):
    """Machine-readable contract validation failure."""

    code: str
    path: str = "$"
    detail: str = ""

    def __str__(self) -> str:
        suffix = f":{self.detail}" if self.detail else ""
        return f"{self.code}@{self.path}{suffix}"


def object_schema(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    additional_properties: bool = False,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required or []),
        "additionalProperties": bool(additional_properties),
    }


def array_schema(
    items: dict[str, Any],
    *,
    min_items: int = 0,
    max_items: int | None = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "array",
        "items": dict(items),
        "minItems": max(0, int(min_items)),
    }
    if max_items is not None:
        schema["maxItems"] = max(0, int(max_items))
    return schema


def string_schema(*, min_length: int = 0, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "string",
        "minLength": max(0, int(min_length)),
    }
    if enum:
        schema["enum"] = [str(item) for item in enum]
    return schema


def nullable_object_schema(properties: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "null"},
            object_schema(dict(properties or {}), additional_properties=True),
        ]
    }


def worker_result_schema(
    output_type: str,
    *,
    data_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the common WorkerResult envelope for one declared output type."""

    return object_schema(
        {
            "task_id": string_schema(min_length=1),
            "agent_id": string_schema(min_length=1),
            "status": string_schema(
                enum=[
                    "completed",
                    "partial",
                    "need_context",
                    "not_executed",
                    "failed",
                    "blocked",
                    "waiting_approval",
                    "proposal_ready",
                ]
            ),
            "output_type": {"type": "string", "enum": [str(output_type)]},
            "payload_schema": string_schema(min_length=1),
            "payload_version": string_schema(min_length=1),
            "payload": {
                "anyOf": [
                    {"type": "null"},
                    dict(data_schema or object_schema({}, additional_properties=True)),
                ]
            },
            "summary": {"type": "string"},
            "data": {
                "anyOf": [
                    {"type": "null"},
                    dict(data_schema or object_schema({}, additional_properties=True)),
                ]
            },
            "evidence_refs": array_schema(
                object_schema({}, additional_properties=True)
            ),
            "artifact_refs": array_schema(
                object_schema({}, additional_properties=True)
            ),
            "missing_items": array_schema(
                object_schema({}, additional_properties=True)
            ),
            "error": nullable_object_schema(),
            "metadata": object_schema({}, additional_properties=True),
        },
        required=[
            "task_id",
            "agent_id",
            "status",
            "output_type",
            "payload_schema",
            "payload_version",
            "payload",
            "summary",
            "data",
            "evidence_refs",
            "artifact_refs",
            "missing_items",
            "error",
            "metadata",
        ],
        additional_properties=True,
    )


def validate_schema(value: Any, schema: dict[str, Any], *, path: str = "$") -> None:
    """Validate the JSON-Schema subset used by Worker contracts.

    Supported keywords are intentionally small and deterministic: ``type``,
    ``anyOf``, ``enum``, ``properties``, ``required``,
    ``additionalProperties``, ``items``, ``minItems``, ``maxItems``, and
    ``minLength``.
    """

    if not isinstance(schema, dict):
        raise WorkerContractViolation("invalid_schema", path, "schema must be object")

    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and any_of:
        failures: list[str] = []
        for candidate in any_of:
            try:
                validate_schema(value, dict(candidate), path=path)
                return
            except WorkerContractViolation as exc:
                failures.append(str(exc))
        raise WorkerContractViolation(
            "no_anyof_schema_matched",
            path,
            " | ".join(failures[:4]),
        )

    expected = schema.get("type")
    if isinstance(expected, list):
        failures: list[str] = []
        for item in expected:
            try:
                validate_schema(value, {**schema, "type": item}, path=path)
                return
            except WorkerContractViolation as exc:
                failures.append(str(exc))
        raise WorkerContractViolation("invalid_type", path, ",".join(map(str, expected)))

    type_map: dict[str, Any] = {
        "object": dict,
        "array": list,
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    if expected:
        wanted = type_map.get(str(expected))
        if wanted is None:
            raise WorkerContractViolation("unsupported_schema_type", path, str(expected))
        if expected in {"integer", "number"} and isinstance(value, bool):
            raise WorkerContractViolation("invalid_type", path, str(expected))
        if not isinstance(value, wanted):
            raise WorkerContractViolation(
                "invalid_type",
                path,
                f"expected={expected},actual={type(value).__name__}",
            )

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        raise WorkerContractViolation(
            "value_not_in_enum",
            path,
            repr(enum_values[:20]),
        )

    if isinstance(value, str):
        minimum = int(schema.get("minLength") or 0)
        if len(value.strip()) < minimum:
            raise WorkerContractViolation(
                "string_too_short",
                path,
                f"minLength={minimum}",
            )

    if isinstance(value, list):
        minimum = int(schema.get("minItems") or 0)
        maximum = schema.get("maxItems")
        if len(value) < minimum:
            raise WorkerContractViolation(
                "array_too_short",
                path,
                f"minItems={minimum}",
            )
        if maximum is not None and len(value) > int(maximum):
            raise WorkerContractViolation(
                "array_too_long",
                path,
                f"maxItems={maximum}",
            )
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_schema(item, item_schema, path=f"{path}[{index}]")

    if isinstance(value, dict):
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        required = schema.get("required")
        required = required if isinstance(required, list) else []
        for key in required:
            if key not in value:
                raise WorkerContractViolation(
                    "missing_required_property",
                    f"{path}.{key}",
                )
        additional_properties = schema.get("additionalProperties")
        if additional_properties is False:
            extras = [key for key in value if key not in properties]
            if extras:
                raise WorkerContractViolation(
                    "additional_property_not_allowed",
                    path,
                    ",".join(map(str, extras[:20])),
                )
        for key, item in value.items():
            child = properties.get(key)
            if isinstance(child, dict):
                validate_schema(item, child, path=f"{path}.{key}")
            elif isinstance(additional_properties, dict):
                validate_schema(
                    item,
                    additional_properties,
                    path=f"{path}.{key}",
                )


def validate_dependency_ids(
    dependency_ids: list[str],
    *,
    known_task_ids: set[str],
    task_id: str,
) -> None:
    for dependency_id in dependency_ids:
        if dependency_id == task_id:
            raise WorkerContractViolation(
                "self_dependency_not_allowed",
                f"$.tasks[{task_id}].dependency_task_ids",
                dependency_id,
            )
        if dependency_id not in known_task_ids:
            raise WorkerContractViolation(
                "unknown_dependency_task",
                f"$.tasks[{task_id}].dependency_task_ids",
                dependency_id,
            )
