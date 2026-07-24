"""Neo4j-backed single-entry financial Agent collaboration runtime.

Imports are intentionally lazy so graph contracts remain usable by offline
migration and validation scripts without requiring the LLM runtime.
"""
from __future__ import annotations

from typing import Any

from .models import (
    AgentCapabilityCard,
    GraphAgentTask,
    GraphWorkerResult,
    MemoryUpdate,
    MissingContextItem,
    ResultStatus,
    SessionMemoryItem,
    TaskStatus,
)


def route_unified_agent_request(*args: Any, **kwargs: Any):
    from .integration import route_unified_agent_request as impl
    return impl(*args, **kwargs)


def execute_unified_agent_request(*args: Any, **kwargs: Any):
    from .integration import execute_unified_agent_request as impl
    return impl(*args, **kwargs)


def execute_control_action(*args: Any, **kwargs: Any):
    from .integration import execute_control_action as impl
    return impl(*args, **kwargs)


def should_use_financial_graph_agent(*args: Any, **kwargs: Any):
    from .integration import should_use_financial_graph_agent as impl
    return impl(*args, **kwargs)


def clear_financial_graph_agent_session(*args: Any, **kwargs: Any):
    from .integration import clear_financial_graph_agent_session as impl
    return impl(*args, **kwargs)


__all__ = [
    "AgentCapabilityCard",
    "GraphAgentTask",
    "GraphWorkerResult",
    "MemoryUpdate",
    "MissingContextItem",
    "ResultStatus",
    "SessionMemoryItem",
    "TaskStatus",
    "clear_financial_graph_agent_session",
    "execute_control_action",
    "execute_unified_agent_request",
    "route_unified_agent_request",
    "should_use_financial_graph_agent",
]
