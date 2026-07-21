"""Compatibility façade for the removed legacy semantic router.

All callers receive the same single Main Coordinator request. This module no
longer imports intent decomposition, parameter extraction, or rule fallback.
"""
from __future__ import annotations

from typing import Any

from agent.collaboration_v2.integration import UnifiedAgentRequest, route_unified_agent_request

RoutedIntent = UnifiedAgentRequest


def route_agent_query(query: str, **_: Any) -> UnifiedAgentRequest:
    return route_unified_agent_request(query)


__all__ = ["RoutedIntent", "route_agent_query"]
