from __future__ import annotations

from agent.collaboration.integration import route_unified_agent_request


def route_agent_request(query: str, **kwargs):
    return route_unified_agent_request(query, **kwargs)


__all__ = ["route_agent_request", "route_unified_agent_request"]
