"""Worker-private views of canonical proposal-only tools."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from agent.tool_engine import get_tool_registry_v2
from agent.tool_runtime import (
    AGENT_MAIN,
    AGENT_WORKER,
    OP_PROPOSAL,
    TOOL_VISIBILITY_WORKER_PRIVATE,
    ToolDefinition,
)


_MEMORY_CONTEXT_KEYS = {
    "account_id",
    "proposal_id",
    "proposal_version",
    "implementation_id",
    "strategy_id",
    "strategy_version",
}


def _proposal_input_schema(definition: ToolDefinition) -> dict[str, Any]:
    input_schema = dict(definition.input_schema or {})
    properties = {
        str(key): dict(value or {})
        for key, value in dict(
            input_schema.get("properties") or {}
        ).items()
    }
    for key, value in properties.items():
        if key in _MEMORY_CONTEXT_KEYS:
            value.setdefault("x-context-source", "memory")
            value.setdefault(
                "description",
                f"当前会话中已确认的 {key}",
            )
        elif any(
            marker in key.lower()
            for marker in ("api_key", "password", "secret", "token")
        ):
            value.setdefault("x-context-source", "system_config")
            value.setdefault("x-sensitivity", "secret")
    input_schema["properties"] = properties
    return input_schema


def _proposal_arguments(plan_context: dict[str, Any]) -> dict[str, Any]:
    task = plan_context["task"]
    execution_context = dict(
        plan_context.get("execution_context") or {}
    )
    resolved_context = dict(
        execution_context.get("resolved_context") or {}
    )
    memory_values = dict(plan_context.get("memory_values") or {})
    task_metadata = dict(task.metadata or {})
    result = {
        "user_id": task.user_id,
        "conversation_id": task.session_id,
        "run_id": task.run_id,
    }
    for key in (
        "account_id",
        "proposal_id",
        "proposal_version",
        "implementation_id",
        "strategy_id",
        "strategy_version",
    ):
        for source in (
            resolved_context,
            memory_values,
            execution_context,
            task_metadata,
        ):
            value = source.get(key)
            if value not in (None, ""):
                result[key] = value
                break
    return result


def build_proposal_tool_definitions() -> list[ToolDefinition]:
    """Clone canonical proposal handlers into a capability-scoped registry.

    The clone preserves the canonical schema, handler, policy, and audit
    metadata while replacing Main-Agent authorization with the private
    Strategy-Guard capability.  No write tool is included.
    """

    result: list[ToolDefinition] = []
    registry = get_tool_registry_v2()
    for definition in registry.list(
        agent_type=AGENT_MAIN,
        operation_type=OP_PROPOSAL,
    ):
        result.append(
            replace(
                definition,
                argument_builder=_proposal_arguments,
                input_schema=_proposal_input_schema(definition),
                produced_outputs=list(
                    dict.fromkeys(
                        [
                            *definition.produced_outputs,
                            "proposal",
                        ]
                    )
                ),
                allowed_agent_types=[AGENT_WORKER],
                allowed_capability_ids=["strategy.proposal"],
                visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
                legacy_names=[],
                tags=list(
                    dict.fromkeys(
                        [
                            *definition.tags,
                            "worker_private",
                            "proposal_only",
                        ]
                    )
                ),
            )
        )
    return result


__all__ = ["build_proposal_tool_definitions"]
