from __future__ import annotations

from typing import Any

from agent.mcp.models import MCPToolInfo
from agent.mcp.security import safe_external_payload
from agent.tools.tool_registry import ToolCategory, ToolSpec
from agent.tools.tool_schemas import ToolPermission


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any] | None) -> tuple[bool, list[str]]:
    args = dict(arguments or {})
    schema = dict(schema or {})
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    errors: list[str] = []
    for name in required:
        if name not in args or args.get(name) in (None, ""):
            errors.append(f"missing_required:{name}")

    simple_types: dict[str, tuple[type, ...]] = {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "object": (dict,),
        "array": (list,),
    }
    for name, value in args.items():
        if name not in properties:
            if schema.get("additionalProperties") is False:
                errors.append(f"unknown_arg:{name}")
            continue
        expected = str((properties.get(name) or {}).get("type") or "")
        allowed = simple_types.get(expected)
        if allowed and value is not None and not isinstance(value, allowed):
            errors.append(f"invalid_type:{name}:{expected}")
    return not errors, errors


def mcp_tool_to_tool_spec(tool: MCPToolInfo, handler) -> ToolSpec:
    metadata = tool.to_dict()
    return ToolSpec(
        name=tool.namespaced_name,
        permission=ToolPermission.READ if tool.mapped else "blocked",
        description=tool.description,
        handler=handler,
        requires_confirmation=False,
        input_schema=safe_external_payload(tool.input_schema, max_chars=4000),
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
                "data": {"type": "object"},
                "warnings": {"type": "array"},
                "errors": {"type": "array"},
            },
            "required": ["success", "data"],
            "additionalProperties": True,
        },
        read_only=tool.effective_read_only,
        has_side_effect=False,
        concurrency_safe=True,
        idempotent=True,
        timeout_seconds=int(max(1, tool.timeout_seconds)),
        retry_policy={"max_attempts": 2, "backoff_seconds": 0.05},
        result_retention="summary",
        category=ToolCategory.READ_QUERY,
    )
