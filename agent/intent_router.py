from __future__ import annotations

from agent.collaboration.integration import route_unified_agent_request


def route_intent(query: str, **kwargs):
    return route_unified_agent_request(query, **kwargs)


__all__ = ["route_intent", "route_unified_agent_request"]
