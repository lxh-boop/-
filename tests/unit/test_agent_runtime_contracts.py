from __future__ import annotations

from agent.schemas import (
    AgentStepStatus,
    AgentTaskStatus,
    PROTECTED_BUSINESS_WRITE_TYPES,
    is_protected_business_write,
)
from agent.tool_engine import OP_READ, OP_WRITE, get_tool_registry_v2
from agent.tool_runtime import validate_input


def test_v2_tool_registry_exposes_runtime_metadata() -> None:
    registry = get_tool_registry_v2()
    assert registry.get("ranking") is not None
    assert registry.get("paper_trade_execute") is not None

    for definition in registry.list():
        metadata = definition.public_view()
        for key in [
            "name",
            "description",
            "input_schema",
            "output_schema",
            "operation_type",
            "allowed_agent_types",
            "requires_approval",
            "runtime_policy",
            "visibility",
            "side_effects",
            "idempotency",
        ]:
            assert key in metadata

    ranking = registry.get("ranking")
    assert ranking is not None
    assert ranking.operation_type == OP_READ
    assert ranking.requires_approval is False
    assert ranking.side_effects == []

    execute = registry.get("paper_trade_execute")
    assert execute is not None
    assert execute.operation_type == OP_WRITE
    assert execute.requires_approval is True


def test_v2_public_tool_view_contains_stable_contract() -> None:
    tools = [
        definition.public_view()
        for definition in get_tool_registry_v2().list()
    ]
    ranking = next(item for item in tools if item["name"] == "market.get_ranking")
    assert ranking["operation_type"] == OP_READ
    assert ranking["requires_approval"] is False
    assert ranking["input_schema"]["type"] == "object"


def test_v2_tool_arg_validation_rejects_missing_required() -> None:
    registry = get_tool_registry_v2()
    assert registry.get("missing_tool") is None
    execute = registry.get("paper_trade_execute")
    assert execute is not None

    errors = validate_input(execute, {"user_id": "u1", "plan_id": "p1"})
    assert "missing_required:confirmation_token" in errors

    errors = validate_input(
        execute,
        {"user_id": "u1", "plan_id": "p1", "confirmation_token": "tok"},
    )
    assert errors == []


def test_runtime_status_and_protected_write_constants_are_stable() -> None:
    assert AgentTaskStatus.CREATED in AgentTaskStatus.ALL
    assert AgentTaskStatus.WAITING_FOR_APPROVAL in AgentTaskStatus.ALL
    assert AgentStepStatus.SUCCEEDED in AgentStepStatus.ALL
    assert "paper_order" in PROTECTED_BUSINESS_WRITE_TYPES
    assert is_protected_business_write("paper_order") is True
    assert is_protected_business_write("agent_tool_call_log") is False
