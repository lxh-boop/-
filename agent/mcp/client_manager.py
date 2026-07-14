from __future__ import annotations

import time
from typing import Any

from agent.mcp.config import EXAMPLE_SERVER_ID, resolve_mcp_server_configs
from agent.mcp.discovery import discover_mcp_tools
from agent.mcp.example_server import call_tool as call_example_tool
from agent.mcp.models import MCPToolInfo
from agent.mcp.schema_adapter import validate_arguments
from agent.mcp.security import safe_external_payload
from agent.tools.tool_schemas import ToolPermission, ToolResult


_CALL_COUNT: dict[str, int] = {}


def parse_mcp_tool_name(namespaced_name: str) -> tuple[str, str]:
    parts = str(namespaced_name or "").split(".", 2)
    if len(parts) != 3 or parts[0] != "mcp" or not parts[1] or not parts[2]:
        raise ValueError(f"invalid_mcp_tool_name:{namespaced_name}")
    return parts[1], parts[2]


def _find_tool(namespaced_name: str, context: dict[str, Any] | None = None) -> MCPToolInfo | None:
    for result in discover_mcp_tools(context):
        if not result.success:
            continue
        for tool in result.tools:
            if tool.namespaced_name == namespaced_name:
                return tool
    return None


def call_mcp_tool(namespaced_name: str, arguments: dict[str, Any] | None = None, *, context: dict[str, Any] | None = None) -> ToolResult:
    context = dict(context or {})
    server_id, tool_name = parse_mcp_tool_name(namespaced_name)
    tool = _find_tool(namespaced_name, context)
    if tool is None:
        return ToolResult(
            success=False,
            message="MCP tool is unavailable or undiscovered.",
            data={
                "status": "unavailable",
                "provider_type": "mcp",
                "server_id": server_id,
                "tool_name": tool_name,
                "fallback_recommended": True,
            },
            warnings=[],
            errors=[f"mcp_tool_unavailable:{namespaced_name}"],
            permission=ToolPermission.READ,
            tool_name=namespaced_name,
        )
    if not tool.mapped or not tool.effective_read_only:
        return ToolResult(
            success=False,
            message="MCP tool is blocked by local read-only policy.",
            data={
                "status": "blocked",
                "provider_type": "mcp",
                "server_id": server_id,
                "tool_name": tool_name,
                "fallback_recommended": True,
            },
            errors=[tool.mapping_error or f"mcp_tool_blocked:{namespaced_name}"],
            permission=ToolPermission.READ,
            tool_name=namespaced_name,
        )

    ok, errors = validate_arguments(tool.input_schema, dict(arguments or {}))
    if not ok:
        return ToolResult(
            success=False,
            message="MCP argument validation failed.",
            data={
                "status": "validation_failed",
                "provider_type": "mcp",
                "server_id": server_id,
                "tool_name": tool_name,
                "fallback_recommended": True,
                "call_attempted": False,
            },
            errors=[f"mcp_args_invalid:{','.join(errors)}"],
            permission=ToolPermission.READ,
            tool_name=namespaced_name,
        )

    failure_mode = str(context.get("mcp_fail_mode") or "").strip().lower()
    if failure_mode == "dependency":
        raise RuntimeError("dependency_error:simulated_mcp_context_failure")
    if failure_mode == "timeout":
        time.sleep(float(context.get("mcp_timeout_sleep_seconds") or 2.0))

    _CALL_COUNT[namespaced_name] = _CALL_COUNT.get(namespaced_name, 0) + 1
    if server_id == EXAMPLE_SERVER_ID:
        raw = call_example_tool(tool_name, dict(arguments or {}), context=context)
    else:
        raise RuntimeError(f"dependency_error:unsupported_mcp_server:{server_id}")

    payload = safe_external_payload(raw, max_chars=5000)
    data = payload.get("data") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("provider_type", "mcp")
    data.setdefault("server_id", server_id)
    data.setdefault("tool_name", tool_name)
    data.setdefault("transport", tool.transport)
    data.setdefault("untrusted_evidence", True)
    return ToolResult(
        success=bool(payload.get("success")) if isinstance(payload, dict) else False,
        message=str(payload.get("message") or "") if isinstance(payload, dict) else "",
        data=data,
        warnings=list(payload.get("warnings") or []) if isinstance(payload, dict) else [],
        errors=list(payload.get("errors") or []) if isinstance(payload, dict) else ["invalid_mcp_payload"],
        permission=ToolPermission.READ,
        tool_name=namespaced_name,
    )


def call_stats() -> dict[str, int]:
    return dict(_CALL_COUNT)


def reset_call_stats() -> None:
    _CALL_COUNT.clear()
