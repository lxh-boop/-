from __future__ import annotations

from typing import Any

from application.contracts import BusinessResult
from agent.mcp.registry_bridge import execute_mcp_tool_as_tool_result, get_mcp_tool_spec, is_mcp_tool_name
from agent.tool_runtime import OP_READ


class McpReadOnlyClient:
    """Read-only MCP bridge for v2 ToolExecutor.

    MCP write/destructive tools are intentionally not exposed here. A tool must be
    discoverable as a mapped, read-only ToolDefinition before execution.
    """

    def invoke(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        context: dict[str, Any] | None = None,
    ) -> BusinessResult:
        name = str(tool_name or "")
        if not is_mcp_tool_name(name):
            return self._blocked(name, "not_mcp_tool")

        spec = get_mcp_tool_spec(name, context)
        if (
            spec is None
            or spec.operation_type != OP_READ
            or not spec.enabled
            or spec.mutates_business_state
        ):
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
        return BusinessResult(
            success=bool(result.success),
            message=str(result.message or ""),
            data=data,
            warnings=list(result.warnings or []),
            errors=list(result.errors or []),
            status=result.status,
        )

    def _blocked(self, tool_name: str, reason: str) -> BusinessResult:
        return BusinessResult(
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
        )


mcp_readonly_client = McpReadOnlyClient()
