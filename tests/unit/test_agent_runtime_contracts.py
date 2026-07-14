from __future__ import annotations

from agent.schemas import (
    AgentStepStatus,
    AgentTaskStatus,
    PROTECTED_BUSINESS_WRITE_TYPES,
    is_protected_business_write,
)
from agent.tools.tool_registry import ToolCategory, get_tool_registry, list_tools, validate_tool_args
from agent.tools.tool_schemas import ToolPermission


def test_tool_registry_exposes_runtime_metadata() -> None:
    registry = get_tool_registry()
    assert "ranking" in registry
    assert "paper_trade_execute" in registry

    for spec in registry.values():
        metadata = spec.metadata()
        for key in [
            "name",
            "description",
            "input_schema",
            "output_schema",
            "read_only",
            "has_side_effect",
            "requires_confirmation",
            "concurrency_safe",
            "idempotent",
            "timeout_seconds",
            "retry_policy",
            "result_retention",
            "category",
        ]:
            assert key in metadata

    ranking = registry["ranking"]
    assert ranking.permission == ToolPermission.READ
    assert ranking.read_only is True
    assert ranking.concurrency_safe is True
    assert ranking.has_side_effect is False

    execute = registry["paper_trade_execute"]
    assert execute.permission == ToolPermission.WRITE
    assert execute.read_only is False
    assert execute.has_side_effect is True
    assert execute.requires_confirmation is True
    assert execute.concurrency_safe is False
    assert execute.category == ToolCategory.PROTECTED_EXECUTION


def test_list_tools_keeps_existing_fields_and_adds_contract() -> None:
    tools = list_tools()
    ranking = next(item for item in tools if item["name"] == "ranking")
    assert ranking["permission"] == ToolPermission.READ
    assert ranking["requires_confirmation"] is False
    assert ranking["read_only"] is True
    assert ranking["input_schema"]["type"] == "object"


def test_tool_arg_validation_rejects_unregistered_and_missing_required() -> None:
    ok, errors = validate_tool_args("missing_tool", {})
    assert ok is False
    assert errors == ["unregistered_tool"]

    ok, errors = validate_tool_args("paper_trade_execute", {"user_id": "u1", "plan_id": "p1"})
    assert ok is False
    assert "missing_required:confirmation_token" in errors

    ok, errors = validate_tool_args(
        "paper_trade_execute",
        {"user_id": "u1", "plan_id": "p1", "confirmation_token": "tok"},
    )
    assert ok is True
    assert errors == []


def test_runtime_status_and_protected_write_constants_are_stable() -> None:
    assert AgentTaskStatus.CREATED in AgentTaskStatus.ALL
    assert AgentTaskStatus.WAITING_FOR_APPROVAL in AgentTaskStatus.ALL
    assert AgentStepStatus.SUCCEEDED in AgentStepStatus.ALL
    assert "paper_order" in PROTECTED_BUSINESS_WRITE_TYPES
    assert is_protected_business_write("paper_order") is True
    assert is_protected_business_write("agent_tool_call_log") is False
