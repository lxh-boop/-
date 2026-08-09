from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.capabilities import CapabilityContract, CapabilityRegistry, OutputSlotGuarantee
from agent.capabilities.contract_validator import CapabilityContractValidator
from agent.capabilities.semantic_slots import SemanticSlotError
from agent.collaboration.context_projection import WorkerInputProjectionMiddleware
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.workers.strategy_guard import run_strategy_guard
from agent.runtime_state import RunSlotStore


def _task(*, input_slot: str = "state.portfolio", output_slot: str = "proposal.rebalance", required_paths=None) -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T02",
        run_id="run",
        session_id="session",
        worker_id="W05",
        assigned_agent="STRATEGY_GUARD",
        objective="生成调整方案",
        user_id="u",
        boundary_id="state_change.proposal",
        contracts=[{
            "contract_id": "T02-C01",
            "required_inputs": [{
                "slot_id": input_slot,
                "required": True,
                "required_paths": list(required_paths or []),
            }],
            "promised_outputs": [{"slot_id": output_slot, "provenance_required": True}],
            "acceptance_rule_ids": ["schema_valid", "proposal_requires_approval", "no_persistent_write"],
            "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
        }],
        resolved_input_bindings=[{
            "source_type": "upstream_task",
            "output_slot_id": input_slot,
            "input_slot_id": input_slot,
            "producer_task_id": "T01",
            "producer_contract_id": "T01-C01",
            "required_paths": list(required_paths or []),
        }],
        expected_output_slots=[output_slot],
    )


def test_open_boundary_accepts_new_runtime_semantic_keys() -> None:
    boundary = CapabilityRegistry().get_boundary("state_change.proposal")
    assert "proposal.*" in boundary.produced_output_patterns
    assert "future_position_proposal" not in boundary.output_slot_examples
    # New task semantics do not require adding a Python Slot class or a new registry item.
    from agent.capabilities.semantic_slots import slot_matches_patterns
    assert slot_matches_patterns("proposal.future_position", boundary.produced_output_patterns)


def test_capability_validator_requires_concrete_materialized_slot() -> None:
    contract = CapabilityContract(
        contract_id="C1",
        description="proposal",
        promised_outputs=[OutputSlotGuarantee("proposal.rebalance")],
        acceptance_rule_ids=["schema_valid"],
    )
    report = CapabilityContractValidator().validate(
        contracts=[contract],
        produced_slots={"proposal.rebalance"},
        materialized_slots={},
        result_status="completed",
        result_payload={"produced_information_slots": ["proposal.rebalance"]},
        evidence_refs=["worker_result:T1"],
    )[0]
    assert report.satisfied_outputs == []
    assert report.missing_outputs == ["proposal.rebalance"]


def test_required_paths_project_only_minimal_worker_input(tmp_path: Path) -> None:
    store = RunSlotStore(tmp_path)
    store.publish(
        run_id="run",
        task_id="T01",
        contract_id="T01-C01",
        slot_id="state.portfolio",
        value={
            "cash_ratio": 0.4,
            "positions": [{"graph_ref": "g1", "weight": 0.2, "unused_blob": "x" * 2000}],
            "orders": [{"id": "should_not_reach_worker"}],
        },
    )
    task = _task(required_paths=["cash_ratio", "positions[*].graph_ref", "positions[*].weight"])
    resolved, audit = WorkerInputProjectionMiddleware(store).project(task, execution_context={})
    assert resolved["state.portfolio"] == {
        "cash_ratio": 0.4,
        "positions": [{"graph_ref": "g1", "weight": 0.2}],
    }
    assert audit[0].projected_chars < audit[0].raw_chars


def test_missing_required_path_is_contract_validation_failure_before_worker(tmp_path: Path) -> None:
    store = RunSlotStore(tmp_path)
    store.publish(
        run_id="run", task_id="T01", contract_id="T01-C01",
        slot_id="state.portfolio", value={"cash_ratio": 0.4},
    )
    task = _task(required_paths=["positions[*].graph_ref"])
    with pytest.raises(SemanticSlotError) as exc:
        WorkerInputProjectionMiddleware(store).project(task, execution_context={})
    assert exc.value.code == "slot_required_path_missing"


def test_slot_store_does_not_publish_declared_but_unmaterialized_output(tmp_path: Path) -> None:
    task = _task()
    result = GraphWorkerResult(
        task_id="T02",
        agent_id="STRATEGY_GUARD",
        status=ResultStatus.PROPOSAL_READY,
        data={"proposal": {"action": "buy"}},
        completion={
            "expected_task_completed": True,
            "completion_status": "completed",
            "produced_information_slots": ["proposal.rebalance"],
        },
    )
    store = RunSlotStore(tmp_path)
    assert store.publish_worker_result(task, result) == []


def test_w05_structural_repair_never_replays_business_context_and_materializes_dynamic_slot() -> None:
    marker = "SECRET_PORTFOLIO_MARKER"

    class FakeLLM:
        def __init__(self) -> None:
            self.calls = []

        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return '{"action":"proposal_ready","proposal":{"note":"truncated"}'
            return json.dumps({
                "action": "proposal_ready",
                "proposal": {"action": "increase_position", "note": "repaired without new facts"},
                "source_task_ids": ["T01"],
                "limitations": [],
                "reason": "形成待审批方案",
                "missing_items": [],
                "requires_approval": True,
                "execution_allowed": False,
            }, ensure_ascii=False)

    task = _task()
    llm = FakeLLM()
    result = run_strategy_guard(
        llm,
        task,
        current_user_request="减少现金并增加持仓",
        resolved_inputs={"state.portfolio": {"marker": marker, "cash_ratio": 0.4}},
        output_dir=".",
        db_path=None,
        default_top_k=10,
        language="zh",
        execution_context={},
    )
    assert result.status == ResultStatus.PROPOSAL_READY
    assert "proposal.rebalance" in result.data["slots"]
    assert len(llm.calls) == 2
    primary_prompt = "\n".join(str(item.get("content") or "") for item in llm.calls[0]["messages"])
    repair_prompt = "\n".join(str(item.get("content") or "") for item in llm.calls[1]["messages"])
    assert marker in primary_prompt
    assert marker not in repair_prompt
    assert llm.calls[1].get("disable_thinking") is True


def test_worker_public_catalog_auto_discovers_private_tool_semantic_outputs() -> None:
    from agent.collaboration.worker_catalog import WorkerDescriptionCatalog
    from agent.collaboration.worker_directory import CapabilityWorkerDirectory

    class FakeToolDirectory:
        def semantic_output_slots(self, worker_role, *, tool_names=None):
            if worker_role != "PORTFOLIO_ANALYST":
                return []
            assert "internal.portfolio.get_state" in set(tool_names or [])
            return ["state.future_margin", "ranking.future_contract"]

    rows = WorkerDescriptionCatalog(
        CapabilityWorkerDirectory(),
        CapabilityRegistry(),
        worker_tool_directory=FakeToolDirectory(),
    ).descriptions(request_mode="analysis")
    w02 = next(row for row in rows if row["worker_id"] == "W02")
    assert w02["private_tool_semantic_outputs"] == [
        "state.future_margin",
        "ranking.future_contract",
    ]
    assert "state.future_margin" in w02["output_slot_examples"]
    assert "ranking.future_contract" in w02["output_slot_examples"]


def test_passthrough_worker_cannot_promise_an_undiscoverable_slot() -> None:
    from agent.collaboration.planner import CoordinatorPlanner

    worker = {
        "output_publication_mode": "private_tool_passthrough",
        "private_tool_semantic_outputs": ["state.portfolio", "state.positions"],
        "supported_boundaries": [
            {"produced_output_patterns": ["state.*"]}
        ],
    }
    assert CoordinatorPlanner._worker_supports_output(worker, "state.portfolio") is True
    assert CoordinatorPlanner._worker_supports_output(worker, "state.future_margin") is False


def test_synthesized_worker_can_publish_new_semantic_slot_within_boundary() -> None:
    from agent.collaboration.planner import CoordinatorPlanner

    worker = {
        "output_publication_mode": "worker_synthesized",
        "private_tool_semantic_outputs": [],
        "supported_boundaries": [
            {"produced_output_patterns": ["proposal.*"]}
        ],
    }
    assert CoordinatorPlanner._worker_supports_output(worker, "proposal.future_position") is True


def _tool_description(name: str) -> str:
    return (
        f"Function: {name}.\n"
        "Applies when: semantic runtime test.\n"
        "Not for: unrelated work.\n"
        "Preconditions: declared contracts.\n"
        "Main inputs: declared semantic slots.\n"
        "Main outputs: declared semantic slots.\n"
        "Side effects: None; read-only."
    )


def test_worker_private_tool_without_explicit_output_contract_is_rejected() -> None:
    from agent.tool_runtime import OP_READ, TOOL_VISIBILITY_WORKER_PRIVATE, ToolDefinition, ToolRegistry

    definition = ToolDefinition(
        name="bad.private.tool",
        display_name="bad.private.tool",
        description=_tool_description("bad.private.tool"),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "required_data_keys": []},
        execution_handler=lambda args, context: {"success": True, "data": {}},
        produced_outputs=["state.example"],
        operation_type=OP_READ,
        allowed_agent_types=["TEST_WORKER"],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )
    with pytest.raises(ValueError, match="requires_explicit_output_contracts"):
        ToolRegistry([definition])


def test_tool_output_contract_materializes_semantic_slot_without_raw_fallback() -> None:
    from agent.tool_runtime import (
        OP_READ,
        TOOL_VISIBILITY_WORKER_PRIVATE,
        ToolDefinition,
        ToolExecutor,
        ToolOutputContract,
        ToolRegistry,
    )

    definition = ToolDefinition(
        name="good.private.tool",
        display_name="good.private.tool",
        description=_tool_description("good.private.tool"),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "required_data_keys": ["payload"]},
        execution_handler=lambda args, context: {"success": True, "data": {"payload": {"x": 1}, "unused": {"large": True}}},
        produced_outputs=["state.example"],
        output_contracts=[
            ToolOutputContract(slot_id="state.example", source_path="data.payload")
        ],
        operation_type=OP_READ,
        allowed_agent_types=["TEST_WORKER"],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )
    result = ToolExecutor(ToolRegistry([definition])).execute(
        "good.private.tool", {}, context={}, agent_type="TEST_WORKER"
    )
    assert result.success is True
    assert result.data["slots"] == {"state.example": {"x": 1}}
    assert "unused" not in result.data["slots"]["state.example"]


def test_required_wildcard_path_allows_business_empty_collection() -> None:
    from agent.capabilities.semantic_slots import missing_required_paths, project_paths

    value = {"positions": []}
    assert missing_required_paths(value, ["positions[*].graph_ref"]) == []
    assert project_paths(value, ["positions[*].graph_ref"]) == {"positions": []}


def test_required_wildcard_path_requires_every_nonempty_record() -> None:
    from agent.capabilities.semantic_slots import missing_required_paths

    value = {"positions": [{"graph_ref": "g1"}, {"weight": 0.2}]}
    assert missing_required_paths(value, ["positions[*].graph_ref"]) == [
        "positions[*].graph_ref"
    ]
