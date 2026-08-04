"""Prompt-only serialization helpers.

These helpers never mutate runtime schemas, contracts, tasks, results, or
validators. They only create smaller read-only views for LLM request payloads.
"""

from __future__ import annotations

import copy
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

_SCHEMA_VALUE_KEYS = (
    "type",
    "enum",
    "const",
    "default",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "minItems",
    "maxItems",
    "pattern",
    "format",
)


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
    """Create a semantics-preserving prompt view of generic capability catalogs.

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


def _compact_value_schema(value: Any) -> Any:
    """Keep exact validating constraints while removing JSON-Schema boilerplate."""

    if not isinstance(value, dict):
        return schema_for_prompt(value)
    result: dict[str, Any] = {}
    for key in _SCHEMA_VALUE_KEYS:
        if key in value:
            result[key] = schema_for_prompt(value[key])
    if "items" in value:
        result["items"] = _compact_value_schema(value["items"])
    if "properties" in value:
        result["properties"] = {
            str(key): _compact_value_schema(item)
            for key, item in dict(value.get("properties") or {}).items()
        }
    if "required" in value:
        result["required"] = [str(item) for item in value.get("required") or []]
    if "additionalProperties" in value:
        result["additionalProperties"] = schema_for_prompt(
            value.get("additionalProperties")
        )
    for keyword in ("anyOf", "oneOf", "allOf"):
        if keyword in value:
            result[keyword] = [
                _compact_value_schema(item) for item in value.get(keyword) or []
            ]
    return result


def _compact_args_schema(value: Any) -> Any:
    """Represent an object args schema without changing any field constraints."""

    schema = schema_for_prompt(value)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return _compact_value_schema(schema)
    return {
        "required": [str(item) for item in schema.get("required") or []],
        "fields": {
            str(key): _compact_value_schema(item)
            for key, item in dict(schema.get("properties") or {}).items()
        },
        "additionalProperties": schema.get("additionalProperties", True),
        "runtime_bound_args": [
            str(item) for item in schema.get("x-runtime-bound-args") or []
        ],
    }


def _reference_output_types(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    properties = dict(value.get("properties") or {})
    output_schema = dict(properties.get("expected_output_type") or {})
    enum_values = [
        str(item) for item in output_schema.get("enum") or [] if str(item)
    ]
    if enum_values:
        return enum_values
    if output_schema.get("type") == "string":
        return ["*"]
    return []


def _compact_semantic_inputs_schema(value: Any) -> Any:
    """Collapse repeated single/array WorkerResult reference schemas.

    The compact role map preserves every semantic role name, required role,
    allowed upstream output type, and cardinality bound. Unsupported schema
    shapes fall back to the original annotation-stripped JSON Schema.
    """

    schema = schema_for_prompt(value)
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return _compact_value_schema(schema)

    required_roles = [str(item) for item in schema.get("required") or []]
    required_set = set(required_roles)
    compact_roles: dict[str, Any] = {}
    for role, raw_role_schema in dict(schema.get("properties") or {}).items():
        role_schema = dict(raw_role_schema or {})
        branches = list(role_schema.get("anyOf") or [])
        if not branches:
            return schema
        allowed_types: list[str] = []
        supports_one = False
        supports_many = False
        max_results = 1
        for branch in branches:
            if not isinstance(branch, dict):
                return schema
            branch_type = str(branch.get("type") or "")
            if branch_type == "object":
                supports_one = True
                allowed_types.extend(_reference_output_types(branch))
            elif branch_type == "array":
                supports_many = True
                item_schema = dict(branch.get("items") or {})
                allowed_types.extend(_reference_output_types(item_schema))
                try:
                    max_results = max(max_results, int(branch.get("maxItems") or 1))
                except (TypeError, ValueError):
                    return schema
            else:
                return schema
        if not allowed_types:
            return schema
        cardinality = (
            "one_or_many"
            if supports_one and supports_many
            else "many"
            if supports_many
            else "one"
        )
        compact_roles[str(role)] = {
            "allowed_output_types": list(dict.fromkeys(allowed_types)),
            "required": str(role) in required_set,
            "cardinality": cardinality,
            "min_results": 1 if str(role) in required_set else 0,
            "max_results": max_results,
        }
    return {
        "required_roles": required_roles,
        "roles": compact_roles,
        "additionalProperties": schema.get("additionalProperties", True),
    }


def planning_catalog_for_prompt(
    catalog: Any,
    *,
    request_mode: str,
) -> list[dict[str, Any]]:
    """Create a smaller but semantically equivalent MainAgent catalog.

    Capabilities that cannot legally pass the existing request-mode/access
    validators are omitted. This does not choose a Worker: the LLM still owns
    Worker selection, task parameters, and all semantic DAG edges among every
    capability that is valid for the current request mode.
    """

    mode = str(request_mode or "analysis").strip().lower()
    compact_workers: list[dict[str, Any]] = []
    for raw_worker in list(catalog or []):
        worker = catalog_for_prompt(raw_worker)
        if not isinstance(worker, dict):
            continue
        # Public MainAgent runs are READ for both analysis and run-local proposal.
        if str(worker.get("access_mode") or "read").lower() == "write":
            continue
        compact_tasks: list[dict[str, Any]] = []
        for raw_task in list(worker.get("task_contracts") or []):
            if not isinstance(raw_task, dict):
                continue
            task = dict(raw_task)
            allowed_modes = {
                str(item).strip().lower()
                for item in task.get("allowed_request_modes") or []
                if str(item).strip()
            }
            if allowed_modes and mode not in allowed_modes:
                continue
            if str(task.get("access_mode") or "read").lower() == "write":
                continue
            task["args_schema"] = _compact_args_schema(task.get("args_schema") or {})
            task["semantic_inputs_schema"] = _compact_semantic_inputs_schema(
                task.get("semantic_inputs_schema") or {}
            )
            # Runtime owns this value and the planner never needs it for selection.
            task.pop("completion_report_source", None)
            compact_tasks.append(task)
        if not compact_tasks:
            continue
        worker["task_contracts"] = compact_tasks
        compact_workers.append(worker)
    return compact_workers


def _set_max_length(schema: dict[str, Any], key: str, limit: int) -> None:
    properties = dict(schema.get("properties") or {})
    field = properties.get(key)
    if isinstance(field, dict) and field.get("type") == "string":
        field["maxLength"] = int(limit)


def _set_array_item_max_length(schema: dict[str, Any], key: str, limit: int) -> None:
    properties = dict(schema.get("properties") or {})
    field = properties.get(key)
    if not isinstance(field, dict):
        return
    items = field.get("items")
    if isinstance(items, dict) and items.get("type") == "string":
        items["maxLength"] = int(limit)


def plan_schema_for_prompt(value: Any) -> Any:
    """Return a prompt schema that omits only fields compiled by runtime code.

    The authoritative runtime ``PLAN_SCHEMA`` remains untouched and validates
    the prepared plan after code has restored the code-owned planning state and
    input-contract fields.
    """

    schema = copy.deepcopy(schema_for_prompt(value))
    properties = dict(schema.get("properties") or {})
    goal = dict(properties.get("goal_contract") or {})
    goal_props = dict(goal.get("properties") or {})
    # access_mode is always compiled to READ by runtime for public Agent runs.
    goal_props.pop("access_mode", None)
    goal["properties"] = goal_props
    goal["required"] = [
        item for item in goal.get("required") or [] if item != "access_mode"
    ]
    _set_max_length(goal, "goal_summary", 300)
    _set_array_item_max_length(goal, "completion_criteria", 240)
    _set_array_item_max_length(goal, "constraints", 200)
    properties["goal_contract"] = goal

    planning = dict(properties.get("planning_state") or {})
    planning_props = dict(planning.get("properties") or {})
    for key in (
        "initial_available_information_slots",
        "final_planned_information_slots",
        "unmet_information_slots",
    ):
        planning_props.pop(key, None)
    planning["properties"] = planning_props
    planning["required"] = ["stop_reason"]
    _set_max_length(planning, "stop_reason", 240)
    properties["planning_state"] = planning

    tasks = dict(properties.get("tasks") or {})
    item_schema = dict(tasks.get("items") or {})
    task_props = dict(item_schema.get("properties") or {})
    task_props["input_contract"] = {
        "type": "object",
        "properties": {},
        "required": [],
        "maxProperties": 0,
        "additionalProperties": False,
    }
    item_schema["properties"] = task_props
    for key, limit in (
        ("objective", 180),
        ("purpose", 240),
        ("why_selected", 240),
    ):
        _set_max_length(item_schema, key, limit)
    for key, limit in (
        ("completion_criteria", 240),
        ("replan_triggers", 180),
        ("constraints", 180),
    ):
        _set_array_item_max_length(item_schema, key, limit)
    expected_output = dict(task_props.get("expected_output") or {})
    for key in ("coverage_requirement", "freshness_requirement", "authority_requirement"):
        _set_max_length(expected_output, key, 180)
    task_props["expected_output"] = expected_output
    failure_policy = dict(task_props.get("failure_policy") or {})
    for key in (
        "missing_parameter",
        "missing_context",
        "tool_failure",
        "business_empty",
        "business_insufficient",
    ):
        _set_max_length(failure_policy, key, 180)
    task_props["failure_policy"] = failure_policy
    tasks["items"] = item_schema
    properties["tasks"] = tasks
    schema["properties"] = properties
    return schema


def coordinator_result_for_replan(value: Any) -> dict[str, Any]:
    """Keep only facts required for a forward-replan decision."""

    result = dict(value or {})
    completion = dict(result.get("completion") or {})
    error = dict(result.get("error") or {}) if result.get("error") else {}
    return {
        "task_id": str(result.get("task_id") or ""),
        "agent_id": str(result.get("agent_id") or ""),
        "status": str(result.get("status") or ""),
        "output_type": str(result.get("output_type") or ""),
        "summary": str(result.get("summary") or "")[:500],
        "confidence": result.get("confidence", 0.0),
        "produced_information_slots": list(
            completion.get("produced_information_slots") or []
        ),
        "missing_information_slots": list(
            completion.get("missing_information_slots") or []
        ),
        "execution_status": str(completion.get("execution_status") or ""),
        "contract_status": str(completion.get("contract_status") or ""),
        "business_status": str(completion.get("business_status") or ""),
        "completion_status": str(completion.get("completion_status") or ""),
        "expected_task_completed": bool(
            completion.get("expected_task_completed")
        ),
        "error": (
            {
                "code": str(error.get("code") or ""),
                "message": str(error.get("message") or "")[:600],
                "component": str(error.get("component") or ""),
                "retryable": bool(error.get("retryable")),
            }
            if error
            else None
        ),
        "warnings": [str(item)[:300] for item in result.get("warnings") or []][:5],
    }


def observation_for_replan(value: Any) -> dict[str, Any]:
    """Remove duplicated completion envelopes from a task observation."""

    row = dict(value or {})
    error = dict(row.get("error") or {}) if row.get("error") else {}
    return {
        "task_id": str(row.get("task_id") or ""),
        "worker_id": str(row.get("worker_id") or ""),
        "task_type": str(row.get("task_type") or ""),
        "expected_output_type": str(row.get("expected_output_type") or ""),
        "actual_output_type": str(row.get("actual_output_type") or ""),
        "status": str(row.get("status") or ""),
        "contract_valid": bool(row.get("contract_valid")),
        "completion_report_valid": bool(row.get("completion_report_valid")),
        "semantic_satisfied": bool(row.get("semantic_satisfied")),
        "produced_information_slots": list(
            row.get("produced_information_slots") or []
        ),
        "missing_information_slots": list(
            row.get("missing_information_slots") or []
        ),
        "failure_kind": str(row.get("failure_kind") or ""),
        "retryable": bool(row.get("retryable")),
        "repairable": bool(row.get("repairable")),
        "replan_recommended": bool(row.get("replan_recommended")),
        "reusable": bool(row.get("reusable")),
        "freeze_reason": str(row.get("freeze_reason") or ""),
        "error": (
            {
                "code": str(error.get("code") or ""),
                "message": str(error.get("message") or "")[:700],
                "component": str(error.get("component") or ""),
                "retryable": bool(error.get("retryable")),
                "blocked_by_task_ids": list(error.get("blocked_by_task_ids") or []),
            }
            if error
            else None
        ),
        "replan_triggers": [
            str(item)[:240] for item in row.get("replan_triggers") or []
        ],
    }


def compact_json_dumps(value: Any) -> str:
    """Serialize without optional whitespace while preserving all values."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


__all__ = [
    "catalog_for_prompt",
    "compact_json_dumps",
    "coordinator_result_for_replan",
    "observation_for_replan",
    "plan_schema_for_prompt",
    "planning_catalog_for_prompt",
    "schema_for_prompt",
]
