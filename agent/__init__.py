"""Financial analysis Agent orchestration layer."""

from agent.schemas import AgentRequest, AgentResponse, ToolCallRecord


def run_agent(*args, **kwargs):
    from agent.agent_core import run_agent as _run_agent

    return _run_agent(*args, **kwargs)


def answer_with_registry(*args, **kwargs):
    from agent.agent_registry import answer_with_registry as _answer_with_registry

    return _answer_with_registry(*args, **kwargs)


__all__ = [
    "AgentRequest",
    "AgentResponse",
    "ToolCallRecord",
    "answer_with_registry",
    "run_agent",
]
