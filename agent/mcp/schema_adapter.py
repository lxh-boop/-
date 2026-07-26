from __future__ import annotations

from typing import Any

from agent.mcp.models import MCPToolInfo
from agent.mcp.security import safe_external_payload
from agent.tool_runtime import (
    OP_READ,
    TOOL_VISIBILITY_PUBLIC,
    ToolDefinition,
)


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


def mcp_tool_to_tool_definition(
    tool: MCPToolInfo,
    handler,
) -> ToolDefinition:
    description = "\n".join(
        [
            f"Function: {tool.description}",
            "Applies when: A mapped read-only MCP source is needed as external evidence.",
            "Not for: Any write, destructive, unmapped, or unallowlisted MCP operation.",
            "Preconditions: The MCP server and tool are enabled, mapped, and allowlisted.",
            "Main inputs: The MCP tool input schema.",
            "Main outputs: Sanitized external evidence and source metadata.",
            "Side effects: None; the bridge permits read-only MCP calls only.",
        ]
    )
    return ToolDefinition(
        name=tool.namespaced_name,
        display_name=tool.tool_name,
        description=description,
        execution_handler=handler,
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
        supported_actions=["retrieve_evidence"],
        supported_objects=["external_evidence"],
        produced_outputs=["mcp_evidence", "sources"],
        operation_type=OP_READ,
        allowed_agent_types=list(tool.effective_allowed_agents),
        permission_scope=OP_READ,
        requires_approval=False,
        runtime_policy={
            "timeout_seconds": int(max(1, tool.timeout_seconds)),
            "retry_policy": {
                "max_attempts": 2,
                "backoff_seconds": 0.05,
            },
        },
        enabled=bool(tool.mapped and tool.effective_read_only),
        sensitivity="external_untrusted",
        visibility=TOOL_VISIBILITY_PUBLIC,
        side_effects=[],
        mutates_business_state=False,
        idempotency="idempotent",
        audit_level="source_trace",
    )
