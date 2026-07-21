"""Removed keyword intent router compatibility façade."""
from __future__ import annotations

SUPPORTED_INTENTS = {"agent_collaboration_v2"}


def route_intent(query: str) -> str:
    del query
    return "agent_collaboration_v2"


__all__ = ["SUPPORTED_INTENTS", "route_intent"]
