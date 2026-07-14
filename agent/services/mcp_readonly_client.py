from __future__ import annotations

from typing import Any

from agent.mcp.registry_bridge import execute_mcp_tool_as_tool_result, get_mcp_tool_spec, is_mcp_tool_name
from agent.tools.tool_schemas import ToolPermission, ToolResult


class McpReadOnlyClient:
    """Read-only MCP bridge for v2 ToolExecutor.

    MCP write/destructive tools are intentionally not exposed here. A tool must be
    discoverable as a mapped, read-only MCP ToolSpec before execution.
    """

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> ToolResult:
        name = str(tool_name or "")
        if not is_mcp_tool_name(name):
            return self._blocked(name, "not_mcp_tool")

        spec = get_mcp_tool_spec(name, context)
        if spec is None or not getattr(spec, "read_only", False) or getattr(spec, "permission", "") != ToolPermission.READ:
            return self._blocked(name, "mcp_readonly_tool_not_allowed")

        result = execute_mcp_tool_as_tool_result(name, dict(arguments or {}), context=context)
        data = dict(result.data or {})
        data.update(
            {
                "read_only": True,
                "mutation_performed": False,
                "mcp_canonical_tool": name,
            }
        )
        return ToolResult(
            success=bool(result.success),
            message=str(result.message or ""),
            data=data,
            warnings=list(result.warnings or []),
            errors=list(result.errors or []),
            permission=ToolPermission.READ,
            tool_name="mcp.readonly.invoke",
            disclaimer=result.disclaimer,
            status=result.status,
            requires_confirmation=False,
        )

    def _blocked(self, tool_name: str, reason: str) -> ToolResult:
        return ToolResult(
            success=False,
            message="MCP tool is not allowed through the read-only bridge.",
            data={
                "status": "blocked",
                "requested_tool_name": tool_name,
                "read_only": True,
                "mutation_performed": False,
            },
            warnings=[],
            errors=[reason],
            permission=ToolPermission.READ,
            tool_name="mcp.readonly.invoke",
        )


mcp_readonly_client = McpReadOnlyClient()
