from __future__ import annotations

import os
from importlib import metadata as importlib_metadata
from typing import Any

from agent.mcp.models import MCPServerConfig


EXAMPLE_SERVER_ID = "local_financial_evidence"
EXAMPLE_TOOL_NAME = "market_risk_summary"
DEFAULT_DISCOVERY_TTL_SECONDS = 300


def mcp_sdk_version() -> str:
    try:
        return importlib_metadata.version("mcp")
    except Exception:
        return "not-installed"


def _bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return default


def _tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return ()


def example_server_config(*, enabled: bool = False, allowed_tools: tuple[str, ...] | None = None, timeout_seconds: float = 5.0) -> MCPServerConfig:
    return MCPServerConfig(
        server_id=EXAMPLE_SERVER_ID,
        name="Local Financial Evidence MCP",
        transport="local_fixture",
        enabled=bool(enabled),
        read_only=True,
        allowed_tools=allowed_tools or (EXAMPLE_TOOL_NAME,),
        timeout_seconds=float(timeout_seconds or 5.0),
        metadata={
            "provider": "project_fixture",
            "sdk_version": mcp_sdk_version(),
            "purpose": "read_only_financial_evidence",
        },
    )


def _server_from_dict(data: dict[str, Any]) -> MCPServerConfig:
    return MCPServerConfig(
        server_id=str(data.get("server_id") or "").strip(),
        name=str(data.get("name") or data.get("server_id") or "").strip(),
        transport=str(data.get("transport") or "local_fixture").strip(),
        command=str(data.get("command") or ""),
        args=_tuple(data.get("args")),
        endpoint=str(data.get("endpoint") or ""),
        enabled=_bool(data.get("enabled"), False),
        read_only=_bool(data.get("read_only"), True),
        allowed_tools=_tuple(data.get("allowed_tools")),
        timeout_seconds=float(data.get("timeout_seconds") or 5.0),
        environment_key_names=_tuple(data.get("environment_key_names")),
        metadata=dict(data.get("metadata") or {}),
    )


def build_mcp_context_from_local_config(local_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    if local_cfg is None:
        try:
            from local_config import load_local_config

            local_cfg = load_local_config()
        except Exception:
            local_cfg = {}

    env_enabled = _bool(os.environ.get("STOCK_APP_MCP_EXAMPLE_ENABLED"), False)
    enabled = _bool((local_cfg or {}).get("mcp_example_enabled"), env_enabled)
    allowed = _tuple((local_cfg or {}).get("mcp_example_allowed_tools")) or (EXAMPLE_TOOL_NAME,)
    timeout_seconds = float((local_cfg or {}).get("mcp_example_timeout_seconds") or 5.0)
    return {
        "servers": [
            example_server_config(
                enabled=enabled,
                allowed_tools=allowed,
                timeout_seconds=timeout_seconds,
            ).to_dict()
        ],
        "discovery_ttl_seconds": int((local_cfg or {}).get("mcp_discovery_ttl_seconds") or DEFAULT_DISCOVERY_TTL_SECONDS),
        "enabled": enabled,
    }


def resolve_mcp_server_configs(context: dict[str, Any] | None = None) -> list[MCPServerConfig]:
    context = dict(context or {})
    mcp_context = context.get("mcp") if isinstance(context.get("mcp"), dict) else context
    raw_servers = mcp_context.get("servers") if isinstance(mcp_context, dict) else None
    if raw_servers is None:
        local = build_mcp_context_from_local_config()
        raw_servers = local.get("servers")

    servers: list[MCPServerConfig] = []
    for raw in raw_servers or []:
        if isinstance(raw, MCPServerConfig):
            servers.append(raw)
        elif isinstance(raw, dict):
            server = _server_from_dict(raw)
            if server.server_id:
                servers.append(server)
    if not servers:
        servers.append(example_server_config(enabled=False))
    return servers


def discovery_ttl_seconds(context: dict[str, Any] | None = None) -> int:
    context = dict(context or {})
    mcp_context = context.get("mcp") if isinstance(context.get("mcp"), dict) else context
    try:
        return max(1, int((mcp_context or {}).get("discovery_ttl_seconds") or DEFAULT_DISCOVERY_TTL_SECONDS))
    except Exception:
        return DEFAULT_DISCOVERY_TTL_SECONDS
