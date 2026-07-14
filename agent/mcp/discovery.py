from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.agent_specs import MARKET_INTELLIGENCE
from agent.mcp.config import discovery_ttl_seconds, mcp_sdk_version, resolve_mcp_server_configs
from agent.mcp.example_server import tool_definitions
from agent.mcp.models import MCPDiscoveryResult, MCPServerConfig, MCPToolInfo
from agent.mcp.security import is_write_like_tool


_DISCOVERY_CACHE: dict[str, tuple[float, MCPDiscoveryResult]] = {}
_DISCOVERY_COUNT: dict[str, int] = {}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_ts() -> float:
    return datetime.now().timestamp()


def _cache_key(server: MCPServerConfig) -> str:
    return "|".join(
        [
            server.server_id,
            server.transport,
            str(server.enabled),
            ",".join(sorted(server.allowed_tools)),
            str(server.timeout_seconds),
        ]
    )


def _raw_tool_definitions(server: MCPServerConfig) -> list[dict[str, Any]]:
    if server.transport in {"local_fixture", "inprocess", "stdio"} and server.server_id == "local_financial_evidence":
        return tool_definitions()
    raise RuntimeError(f"dependency_error:unsupported_mcp_transport:{server.transport}:{server.server_id}")


def _tool_info(server: MCPServerConfig, raw: dict[str, Any], discovered_at: str) -> MCPToolInfo:
    tool_name = str(raw.get("name") or "").strip()
    description = str(raw.get("description") or "")
    annotations = dict(raw.get("annotations") or {})
    declared_read_only = bool(annotations.get("readOnlyHint", True))
    write_like = is_write_like_tool(tool_name, description, annotations)
    tool_read_only = declared_read_only and not write_like
    allowlisted = tool_name in set(server.allowed_tools)
    mapped = bool(server.enabled and server.read_only and tool_read_only and allowlisted)
    effective_permission = "read" if mapped else "blocked"
    mapping_error = ""
    if not allowlisted:
        mapping_error = "tool_not_in_server_allowlist"
    elif not server.read_only or not tool_read_only:
        mapping_error = "mcp_write_tool_blocked"

    return MCPToolInfo(
        server_id=server.server_id,
        server_name=server.name,
        tool_name=tool_name,
        namespaced_name=f"mcp.{server.server_id}.{tool_name}",
        description=description,
        input_schema=dict(raw.get("input_schema") or {"type": "object", "properties": {}}),
        annotations=annotations,
        server_enabled=server.enabled,
        server_read_only=server.read_only,
        tool_read_only=tool_read_only,
        allowlisted=allowlisted,
        mapped=mapped,
        mapping_error=mapping_error,
        discovered_at=discovered_at,
        transport=server.transport,
        timeout_seconds=server.timeout_seconds,
        effective_read_only=mapped,
        effective_permission=effective_permission,
        effective_allowed_agents=(MARKET_INTELLIGENCE,) if mapped else (),
        requires_confirmation=False,
        metadata={
            "provider_type": "mcp",
            "sdk_version": mcp_sdk_version(),
            "local_security_source": "server_tool_allowlist",
        },
    )


def discover_mcp_tools(context: dict[str, Any] | None = None, *, force: bool = False) -> list[MCPDiscoveryResult]:
    ttl = discovery_ttl_seconds(context)
    results: list[MCPDiscoveryResult] = []
    for server in resolve_mcp_server_configs(context):
        if not server.enabled:
            results.append(
                MCPDiscoveryResult(
                    server_id=server.server_id,
                    server_name=server.name,
                    enabled=False,
                    transport=server.transport,
                    success=True,
                    discovered_at=_now_text(),
                    tools=(),
                    cached=False,
                    metadata={"sdk_version": mcp_sdk_version(), "skipped": "server_disabled"},
                )
            )
            continue

        key = _cache_key(server)
        cached = _DISCOVERY_CACHE.get(key)
        if cached and not force and (_now_ts() - cached[0]) < ttl:
            result = cached[1]
            results.append(
                MCPDiscoveryResult(
                    server_id=result.server_id,
                    server_name=result.server_name,
                    enabled=result.enabled,
                    transport=result.transport,
                    success=result.success,
                    discovered_at=result.discovered_at,
                    tools=result.tools,
                    error=result.error,
                    cached=True,
                    metadata=dict(result.metadata),
                )
            )
            continue

        _DISCOVERY_COUNT[server.server_id] = _DISCOVERY_COUNT.get(server.server_id, 0) + 1
        discovered_at = _now_text()
        try:
            tools = tuple(_tool_info(server, raw, discovered_at) for raw in _raw_tool_definitions(server))
            result = MCPDiscoveryResult(
                server_id=server.server_id,
                server_name=server.name,
                enabled=True,
                transport=server.transport,
                success=True,
                discovered_at=discovered_at,
                tools=tools,
                cached=False,
                metadata={"sdk_version": mcp_sdk_version(), "tool_count": len(tools)},
            )
        except Exception as exc:
            result = MCPDiscoveryResult(
                server_id=server.server_id,
                server_name=server.name,
                enabled=True,
                transport=server.transport,
                success=False,
                discovered_at=discovered_at,
                tools=(),
                error=f"{type(exc).__name__}:{exc}",
                cached=False,
                metadata={"sdk_version": mcp_sdk_version()},
            )
        _DISCOVERY_CACHE[key] = (_now_ts(), result)
        results.append(result)
    return results


def reset_discovery_cache() -> None:
    _DISCOVERY_CACHE.clear()
    _DISCOVERY_COUNT.clear()


def discovery_stats() -> dict[str, Any]:
    return {
        "cache_entries": len(_DISCOVERY_CACHE),
        "discovery_count": dict(_DISCOVERY_COUNT),
    }
