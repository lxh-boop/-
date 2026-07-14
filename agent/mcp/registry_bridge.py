from __future__ import annotations

from typing import Any

from agent.agent_specs import MARKET_INTELLIGENCE
from agent.mcp.client_manager import call_mcp_tool, parse_mcp_tool_name
from agent.mcp.config import EXAMPLE_SERVER_ID, EXAMPLE_TOOL_NAME
from agent.mcp.discovery import discover_mcp_tools
from agent.mcp.models import MCPToolInfo
from agent.mcp.schema_adapter import mcp_tool_to_tool_spec
from agent.tools.tool_schemas import ToolResult


def is_mcp_tool_name(tool_name: str) -> bool:
    return str(tool_name or "").startswith("mcp.")


def _mapped_tools(context: dict[str, Any] | None = None) -> list[MCPToolInfo]:
    tools: list[MCPToolInfo] = []
    for result in discover_mcp_tools(context):
        if not result.success:
            continue
        tools.extend(tool for tool in result.tools if tool.mapped)
    return tools


def _handler_for(tool_name: str):
    def _handler(**kwargs):
        return execute_mcp_tool_as_tool_result(tool_name, kwargs).to_dict()

    return _handler


def list_mcp_tool_specs(context: dict[str, Any] | None = None, *, role: str | None = None, query: str = "") -> list[Any]:
    selected: list[Any] = []
    for tool in _mapped_tools(context):
        if role and role not in set(tool.effective_allowed_agents):
            continue
        if query and not _is_relevant(tool, query):
            continue
        selected.append(mcp_tool_to_tool_spec(tool, _handler_for(tool.namespaced_name)))
    return selected


def get_mcp_tool_spec(tool_name: str, context: dict[str, Any] | None = None):
    if not is_mcp_tool_name(tool_name):
        return None
    for spec in list_mcp_tool_specs(context):
        if spec.name == tool_name:
            return spec
    return None


def validate_mcp_tool_allowed_for_role(role: str, tool_name: str, context: dict[str, Any] | None = None) -> None:
    if not is_mcp_tool_name(tool_name):
        raise PermissionError(f"not_mcp_tool:{tool_name}")
    for tool in _mapped_tools(context):
        if tool.namespaced_name == tool_name and role in set(tool.effective_allowed_agents):
            return
    raise PermissionError(f"mcp_tool_not_allowed_for_agent:{role}:{tool_name}")


def _is_relevant(tool: MCPToolInfo, query: str) -> bool:
    text = f"{query} {tool.description} {tool.tool_name}".lower()
    relevant_markers = [
        "portfolio",
        "position",
        "risk",
        "stable",
        "robust",
        "recommend",
        "holding",
        "持仓",
        "组合",
        "风险",
        "稳健",
        "推荐",
        "模拟盘",
    ]
    return any(marker in text for marker in relevant_markers)


def select_relevant_mcp_tools(
    *,
    role: str = MARKET_INTELLIGENCE,
    query: str = "",
    context: dict[str, Any] | None = None,
    limit: int = 1,
) -> list[Any]:
    if role != MARKET_INTELLIGENCE:
        return []
    specs = list_mcp_tool_specs(context, role=role, query=query)
    return specs[: max(0, int(limit or 1))]


def execute_mcp_tool_as_tool_result(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> ToolResult:
    return call_mcp_tool(tool_name, dict(arguments or {}), context=context)


def default_example_tool_name() -> str:
    return f"mcp.{EXAMPLE_SERVER_ID}.{EXAMPLE_TOOL_NAME}"


def mcp_call_metadata(
    *,
    tool_name: str,
    result: dict[str, Any] | None,
    runtime_reliability: dict[str, Any] | None = None,
    fallback_used: bool = False,
) -> dict[str, Any]:
    server_id = ""
    raw_tool_name = ""
    try:
        server_id, raw_tool_name = parse_mcp_tool_name(tool_name)
    except Exception:
        pass
    data = dict((result or {}).get("data") or {})
    reliability = dict(runtime_reliability or {})
    reliability_mcp = reliability.get("mcp") if isinstance(reliability.get("mcp"), dict) else {}
    return {
        "provider_type": "mcp",
        "server_id": server_id or str(data.get("server_id") or ""),
        "tool_name": raw_tool_name or str(data.get("tool_name") or tool_name),
        "transport": str(data.get("transport") or "local_fixture"),
        "elapsed_ms": reliability.get("elapsed_ms"),
        "retry_count": reliability.get("retry_count", 0),
        "circuit_state": reliability.get("circuit_state", ""),
        "status": "success" if (result or {}).get("success") else "failed",
        "error_type": reliability.get("error_type") or ",".join(str(item) for item in ((result or {}).get("errors") or [])[:2]),
        "fallback_used": bool(fallback_used or data.get("fallback_used") or reliability_mcp.get("fallback_used")),
    }


def summarize_mcp_usage(agent_result: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(agent_result or {})
    orchestration = data.get("orchestration") if isinstance(data.get("orchestration"), dict) else {}
    nested = data.get("result") if isinstance(data.get("result"), dict) else {}
    if isinstance(nested.get("data"), dict):
        orchestration = nested.get("data") or orchestration
    calls = []
    for call in orchestration.get("tool_calls") or data.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        tool_name = str(call.get("tool_name") or call.get("intent") or "")
        if is_mcp_tool_name(tool_name):
            reliability = dict(call.get("runtime_reliability") or {})
            calls.append(
                {
                    "tool_name": tool_name,
                    "success": bool(call.get("success")),
                    "elapsed_ms": reliability.get("elapsed_ms"),
                    "retry_count": reliability.get("retry_count"),
                    "circuit_state": reliability.get("circuit_state"),
                    "error_type": reliability.get("error_type"),
                }
            )
    fallbacks = []
    for audit in orchestration.get("replan_audit") or []:
        if isinstance(audit, dict) and "mcp" in str(audit.get("trigger_reason") or ""):
            fallbacks.append(audit)
    return {
        "used_mcp": bool(calls),
        "mcp_tool_calls": calls,
        "mcp_fallbacks": fallbacks,
    }
