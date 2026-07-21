from __future__ import annotations

from pathlib import Path

import pytest

from agent.agent_specs import SUPERVISOR
from agent.capability_index import CapabilityIndexRepository, build_trusted_capability_index
from agent.router import route_agent_query
from agent.tool_engine import (
    AGENT_MAIN,
    AGENT_READ,
    OP_READ,
    OP_WRITE,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    execute_tool,
    get_tool_registry_v2,
)


VALID_DESCRIPTION = "\n".join(
    [
        "Function: demo tool.",
        "Applies when: tests need a deterministic tool.",
        "Not for: production use.",
        "Preconditions: none.",
        "Main inputs: none.",
        "Main outputs: demo_result.",
        "Side effects: None; read-only.",
    ]
)


def _demo_definition(
    name: str = "demo.read",
    *,
    operation_type: str = OP_READ,
    legacy_names: list[str] | None = None,
    allowed_agent_types: list[str] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        display_name="Demo",
        description=VALID_DESCRIPTION,
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "required_data_keys": ["demo_result"]},
        execution_handler=lambda args, context: {
            "success": True,
            "message": "ok",
            "data": {"demo_result": 1},
            "tool_name": name,
        },
        operation_type=operation_type,
        allowed_agent_types=allowed_agent_types or [AGENT_MAIN, AGENT_READ],
        requires_approval=operation_type == OP_WRITE,
        legacy_names=legacy_names or [],
    )


def test_phase11_recommendation_with_reduce_words_stays_readonly_task_plan() -> None:
    routed = route_agent_query(
        "recommend a more stable target portfolio after reducing high concentration",
        enable_llm=False,
        context={"user_id": "u1", "session_id": "s1", "default_top_k": 10},
    )
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]
    intents = [task["intent"] for task in routed.decomposition["tasks"]]

    assert routed.intent == "multi_intent"
    assert routed.execution_route == "read_only_dag"
    assert trace["execution_task_source"] == "task_plan"
    assert trace["semantic_goal"]["canonical_action"] == "construct_recommendation"
    assert trace["semantic_goal"]["requires_write"] is False
    assert "one_time_position_operation" not in intents
    assert {"portfolio_state", "portfolio_risk", "ranking"} <= set(intents)


def test_phase11_manual_change_becomes_proposal_flow_not_direct_commit() -> None:
    routed = route_agent_query(
        "trim stock 603986 by half",
        enable_llm=False,
        context={"user_id": "u1", "session_id": "s1", "default_top_k": 10},
    )
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert routed.intent == "one_time_position_operation"
    assert routed.execution_route == "proposal_flow"
    assert trace["semantic_goal"]["canonical_action"] == "manual_change"
    assert trace["semantic_goal"]["requires_write"] is True
    assert trace["semantic_goal"]["explicit_parameters"]["stock_code"] == "603986"
    assert trace["legacy_shadow"]["new_will_execute"] is False


def test_phase11_legacy_shadow_records_old_and_new_mainline() -> None:
    routed = route_agent_query(
        "show top 10 ranking and analyze each stock",
        enable_llm=False,
        context={"user_id": "u1", "session_id": "s1", "default_top_k": 10},
    )
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]
    shadow = trace["legacy_shadow"]

    assert routed.intent == "multi_intent"
    assert routed.execution_route == "read_only_dag"
    assert trace["execution_task_source"] == "task_plan"
    assert shadow["legacy_intent"] == "multi_intent"
    assert shadow["legacy_tasks"]
    assert [task["intent"] for task in shadow["new_task_plan"]["tasks"]] == ["ranking", "stock_analysis"]


def test_phase11_tool_registry_validates_duplicate_names_and_description_template() -> None:
    with pytest.raises(ValueError, match="duplicate_tool_name"):
        ToolRegistry(
            [
                _demo_definition("demo.one", legacy_names=["demo_alias"]),
                _demo_definition("demo.two", legacy_names=["demo_alias"]),
            ]
        )

    with pytest.raises(ValueError, match="invalid_tool_description_template"):
        ToolRegistry(
            [
                ToolDefinition(
                    name="demo.bad",
                    display_name="Bad",
                    description="too short",
                    input_schema={"type": "object", "properties": {}, "required": []},
                    output_schema={"type": "object", "required_data_keys": []},
                    execution_handler=lambda args, context: {},
                )
            ]
        )


def test_phase11_tool_executor_blocks_unregistered_and_unauthorized_operations() -> None:
    registry = ToolRegistry([_demo_definition("demo.write", operation_type=OP_WRITE)])
    executor = ToolExecutor(registry)

    missing = executor.execute("missing.tool", {}, agent_type=AGENT_READ)
    assert missing.success is False
    assert missing.error_type == "unregistered_tool"

    read_worker_write = executor.execute("demo.write", {}, agent_type=AGENT_READ)
    assert read_worker_write.success is False
    assert read_worker_write.error_type == "unauthorized_operation_type"

    approval_required = executor.execute("demo.write", {}, agent_type=AGENT_MAIN)
    assert approval_required.success is False
    assert approval_required.error_type == "approval_required"


def test_phase11_tool_executor_standardizes_outputs_and_validates_inputs(tmp_path: Path) -> None:
    registry = ToolRegistry([_demo_definition("demo.read")])
    result = ToolExecutor(registry).execute("demo.read", {}, context={"output_dir": tmp_path}, agent_type=AGENT_READ)

    assert result.success is True
    assert result.schema_version == "tool-result-v1"
    assert result.data == {"demo_result": 1}
    assert result.duration_ms >= 0
    assert "runtime_reliability" in result.to_legacy_dict()

    invalid = execute_tool("stock_analysis", {}, context={"output_dir": tmp_path}, agent_type=AGENT_READ)
    assert invalid.success is False
    assert invalid.error_type == "input_validation"
    assert "missing_required:stock_code" in invalid.error_message


def test_phase11_capability_index_uses_unified_tool_registry_read_view() -> None:
    registry_records = get_tool_registry_v2().public_index_records(agent_type=AGENT_READ)
    assert registry_records
    assert all("execution_handler" not in record for record in registry_records)

    index = build_trusted_capability_index()
    portfolio = next(record for record in index.records if record.capability_id == "tool:portfolio_state")
    assert "portfolio.get_state" in portfolio.registered_tool_names

    supervisor_view = CapabilityIndexRepository(index).query(
        agent_identity=SUPERVISOR,
        goal_action="query",
        missing_outputs=["portfolio_state"],
        permission_scope="read",
        limit=2,
    )
    assert supervisor_view
    assert all("implementation_files" not in item for item in supervisor_view)
