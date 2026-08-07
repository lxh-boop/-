from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.capabilities import (
    CapabilityContract,
    CapabilityRegistry,
    CapabilityTask,
    InputSlotRequirement,
    OutputSlotGuarantee,
    SlotBinder,
    WorkerAssignmentValidator,
)
from agent.collaboration.completion import canonicalize_completion_report
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.worker_catalog import ProgressiveWorkerCatalog
from agent.collaboration.worker_directory import CapabilityWorkerDirectory, GRAPH_RELATION_RETRIEVER
from agent.collaboration.workers.entity_analysis import _resolved_items as entity_resolved_items
from agent.collaboration.workers.report_writer import _terminal_inputs as report_terminal_inputs
from agent.tool_dag.executor import ToolDagExecutor
from agent.tool_dag.contracts import ToolDagPlan, ToolDagTask
from agent.tool_runtime import ToolDefinition, ToolRegistry, UnifiedToolResult
from agent.tool_runtime.contracts import OP_READ, TOOL_VISIBILITY_WORKER_PRIVATE
from agent.worker_tools.registry import WorkerToolDirectory
from agent.collaboration.workers.slot_inputs import contract_input_slot_ids, contract_required_slot_ids
from agent.tool_dag.planner import WorkerToolDagPlanner


def _description(name: str) -> str:
    return (
        f"Function: {name}.\n"
        "Applies when: required slots are available.\n"
        "Not for: unrelated work.\n"
        "Preconditions: validated inputs.\n"
        "Main inputs: slot values.\n"
        "Main outputs: promised slots.\n"
        "Side effects: none."
    )


def _tool(name: str, required: list[str], produced: list[str]) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        display_name=name,
        description=_description(name),
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
        execution_handler=lambda args, context: {},
        produced_outputs=produced,
        required_input_slots=required,
        operation_type=OP_READ,
        allowed_agent_types=[GRAPH_RELATION_RETRIEVER],
        visibility=TOOL_VISIBILITY_WORKER_PRIVATE,
    )


def _graph_task(worker_id: str = "W03") -> CapabilityTask:
    return CapabilityTask(
        task_id="T01",
        worker_id=worker_id,
        boundary_id="graph_relation.retrieval",
        objective="读取实体关系",
        contracts=[CapabilityContract(
            contract_id="T01-C01",
            description="读取关系事实",
            required_inputs=[InputSlotRequirement("authoritative_entity_refs")],
            promised_outputs=[OutputSlotGuarantee("graph_relation_facts")],
            acceptance_rule_ids=["schema_valid", "provenance_present", "no_persistent_write"],
        )],
    )


def test_worker_catalog_is_progressive() -> None:
    directory = CapabilityWorkerDirectory()
    catalog = ProgressiveWorkerCatalog(directory, CapabilityRegistry())
    summaries = catalog.summaries(request_mode="analysis")
    assert {row["worker_id"] for row in summaries} == {"W01", "W02", "W03", "W04", "W06", "W07", "W09"}
    w03 = next(row for row in summaries if row["worker_id"] == "W03")
    assert "short_description" in w03
    assert "full_description" not in w03
    assert "private_tool_ids" not in w03
    details = catalog.load_details(["W03"], request_mode="analysis")
    assert [row["worker_id"] for row in details] == ["W03"]
    assert details[0]["full_description"]
    assert "private_tool_ids" not in details[0]
    assert details[0]["private_tool_details_visible_to_main_agent"] is False


def test_main_agent_selects_worker_runtime_only_validates() -> None:
    task = _graph_task("W03")
    bindings = SlotBinder().bind([task], initial_information_slots={"authoritative_entity_refs"})
    resolved = WorkerAssignmentValidator(
        CapabilityRegistry(), CapabilityWorkerDirectory()
    ).validate([task], bindings=bindings, request_mode="analysis")
    assert resolved[0].assigned_worker_id == "W03"
    assert resolved[0].resolution_reason == "main_agent_selected_worker;runtime_assignment_validated"
    bad = _graph_task("W01")
    bad_bindings = SlotBinder().bind([bad], initial_information_slots={"authoritative_entity_refs"})
    with pytest.raises(Exception, match="selected_worker_does_not_support_boundary"):
        WorkerAssignmentValidator(CapabilityRegistry(), CapabilityWorkerDirectory()).validate(
            [bad], bindings=bad_bindings, request_mode="analysis"
        )


def test_tool_catalog_summary_then_selected_details() -> None:
    directory = WorkerToolDirectory(ToolRegistry([
        _tool("graph.neighborhood", ["authoritative_entity_refs"], ["graph_relation_facts"]),
        _tool("graph.paths", ["source_entity_refs", "target_entity_refs"], ["financial_relation_paths"]),
    ]))
    compatible = directory.compatible_tool_names(
        GRAPH_RELATION_RETRIEVER,
        available_context_keys={"authoritative_entity_refs"},
    )
    assert compatible == ["graph.neighborhood"]
    summaries = directory.summary_catalog(GRAPH_RELATION_RETRIEVER, tool_names=compatible)
    assert "input_schema" not in summaries[0]
    assert summaries[0]["required_input_slots"] == ["authoritative_entity_refs"]
    details = directory.load_details(GRAPH_RELATION_RETRIEVER, ["graph.neighborhood"])
    assert [row["tool_id"] for row in details] == ["graph.neighborhood"]
    assert "input_schema" in details[0]
    assert "graph.paths" not in {row["tool_id"] for row in details}


def test_nested_slot_publication_satisfies_tool_node_contract() -> None:
    task = ToolDagTask(
        tool_task_id="TT1",
        tool_name="graph.neighborhood",
        objective="读取关系",
        expected_output_keys=["graph_relation_facts"],
    )
    result = UnifiedToolResult(
        success=True,
        tool_name="graph.neighborhood",
        data={
            "slots": {"graph_relation_facts": {"facts": []}},
            "produced_information_slots": ["graph_relation_facts"],
        },
    )
    record = ToolDagExecutor._record_from_result(task, result)
    assert record.status == "succeeded"
    assert record.contract_valid is True
    assert record.missing_output_keys == []


def _analysis_task() -> GraphAgentTask:
    bindings = []
    for slot, producer in [
        ("entity_external_evidence", "T01"),
        ("entity_model_signals", "T02"),
        ("entity_analysis", "T04"),
    ]:
        bindings.append({
            "source_type": "upstream_task",
            "output_slot_id": slot,
            "input_slot_id": slot,
            "producer_task_id": producer,
            "producer_contract_id": f"{producer}-C01",
        })
    return GraphAgentTask(
        task_id="T09",
        run_id="run",
        session_id="session",
        worker_id="W09",
        assigned_agent="ENTITY_ANALYST",
        objective="分析实体",
        user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "T09-C01",
            "required_inputs": [
                {"slot_id": "entity_external_evidence", "required": True},
                {"slot_id": "entity_model_signals", "required": False},
            ],
        }],
        resolved_input_bindings=bindings,
    )


def test_entity_analysis_consumes_slot_identity_not_worker_result_type() -> None:
    task = _analysis_task()
    rows = entity_resolved_items(task, {
        "entity_external_evidence": {"record_count": 2},
        "entity_model_signals": {"found": True},
    })
    assert {row["slot_id"] for row in rows} == {
        "entity_external_evidence", "entity_model_signals"
    }
    assert next(row for row in rows if row["slot_id"] == "entity_external_evidence")["source_task_ids"] == ["T01"]
    assert all("output_type" not in row for row in rows)


def test_report_writer_consumes_terminal_slots_only() -> None:
    task = _analysis_task()
    report_task = GraphAgentTask(
        task_id="TR", run_id="run", session_id="session", worker_id="W06",
        assigned_agent="REPORT_WRITER", objective="报告", user_id="u",
        boundary_id="result.composition",
        contracts=[{"contract_id": "TR-C01", "required_inputs": [{"slot_id": "entity_analysis", "required": True}]}],
        resolved_input_bindings=[{
            "source_type": "upstream_task", "output_slot_id": "entity_analysis",
            "input_slot_id": "entity_analysis", "producer_task_id": "T04",
            "producer_contract_id": "T04-C01",
        }],
    )
    safe, task_ids = report_terminal_inputs(
        report_task,
        {
            "entity_external_evidence": {"record_count": 2},
            "entity_model_signals": {"found": True},
            "entity_analysis": {"facts": [], "analysis": [], "source_task_ids": ["T04"]},
        },
    )
    assert [row["slot_id"] for row in safe] == ["entity_analysis"]
    assert task_ids == ["T04"]


def test_completion_canonicalization_clears_stale_failure() -> None:
    task = GraphAgentTask(
        task_id="T01", run_id="run", session_id="s", worker_id="W03",
        assigned_agent="GRAPH_RELATION_RETRIEVER", objective="关系", user_id="u",
        boundary_id="graph_relation.retrieval",
        contracts=[{"contract_id": "T01-C01", "criticality": "required"}],
        expected_output_slots=["graph_relation_facts"],
    )
    report = SimpleNamespace(status="completed", to_dict=lambda: {"status": "completed"})
    status, completion, satisfied = canonicalize_completion_report(
        task,
        result_status=ResultStatus.PARTIAL,
        completion={"failure_kind": "worker_execution_failure", "limitations": ["stale"]},
        contract_reports=[report],
        produced_slots=["graph_relation_facts"],
        result_data={"slots": {"graph_relation_facts": {}}},
    )
    assert satisfied is True
    assert status == ResultStatus.COMPLETED
    assert completion["execution_status"] == "succeeded"
    assert completion["failure_kind"] == "none"
    assert completion["limitations"] == []


def test_upfront_main_agent_uses_intent_worker_calls_and_worker_dag() -> None:
    from agent.collaboration.planner import CoordinatorPlanner

    class FakeLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def generate_json(self, **kwargs):
            self.calls.append(kwargs)
            stage = kwargs["stage"]
            if stage == "upfront_user_intent_planning":
                payload = {
                    "intent_summary": "诊断当前系统运行问题并给出用户可读结论",
                    "needs": [{"description": "诊断当前系统运行状态与失败类型", "required": True}],
                    "constraints": [],
                    "scope_note": "当前系统运行",
                    "effect_limit": "read",
                }
            elif stage == "upfront_worker_call_selection":
                user_prompt = kwargs["messages"][1]["content"]
                assert '"user_request":' not in user_prompt
                assert "worker_descriptions" in user_prompt
                assert "full_description" in user_prompt
                payload = {
                    "worker_calls": [
                        {
                            "call_id": "WC01",
                            "worker_id": "W07",
                            "objective": "形成系统诊断",
                            "covers_need_ids": ["N01"],
                            "desired_output_slots": ["system_diagnosis"],
                        },
                        {
                            "call_id": "WC02",
                            "worker_id": "W06",
                            "objective": "生成面向用户的自然语言诊断报告",
                            "covers_need_ids": ["N_FINAL"],
                            "desired_output_slots": ["user_facing_report"],
                        },
                    ],
                    "selection_reason": "W07完成诊断，W06负责最终表达。",
                }
            elif stage == "upfront_worker_dag_planning":
                user_prompt = kwargs["messages"][1]["content"]
                assert '"user_request":' not in user_prompt
                assert "selected_worker_calls" in user_prompt
                payload = {
                    "tasks": [
                        {
                            "worker_id": "W07",
                            "boundary_id": "system.diagnosis",
                            "objective": "诊断系统",
                            "effect_limit": "read",
                            "priority": 1,
                            "business_parameters": {},
                            "contracts": [{
                                "description": "形成系统诊断",
                                "required_inputs": [
                                    {"slot_id": "runtime_context", "required": True, "cardinality": "one"},
                                    {"slot_id": "current_user_request", "required": True, "cardinality": "one"},
                                ],
                                "promised_outputs": [{"slot_id": "system_diagnosis", "provenance_required": True}],
                                "acceptance_rule_ids": ["schema_valid", "failure_kind_classified", "no_persistent_write"],
                                "forbidden_output_slots": [],
                                "criticality": "required",
                                "effect_limit": "read",
                            }],
                        },
                        {
                            "worker_id": "W06",
                            "boundary_id": "result.composition",
                            "objective": "生成用户报告",
                            "effect_limit": "read",
                            "priority": 2,
                            "business_parameters": {},
                            "contracts": [{
                                "description": "把系统诊断组织为用户自然语言",
                                "required_inputs": [{"slot_id": "system_diagnosis", "required": True, "cardinality": "one"}],
                                "promised_outputs": [
                                    {"slot_id": "user_facing_report", "provenance_required": True},
                                    {"slot_id": "goal_completion_summary", "provenance_required": True},
                                ],
                                "acceptance_rule_ids": ["schema_valid", "claims_traceable", "goal_coverage", "no_persistent_write"],
                                "forbidden_output_slots": [],
                                "criticality": "required",
                                "effect_limit": "read",
                            }],
                        },
                    ]
                }
            else:
                raise AssertionError(stage)
            kwargs["validator"](payload)
            return payload

    fake = FakeLLM()
    tasks, metadata = CoordinatorPlanner(
        CapabilityWorkerDirectory(), llm_service=fake
    ).plan(
        query="诊断系统",
        request_mode="analysis",
        session_id="s",
        run_id="r",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )
    assert [call["stage"] for call in fake.calls] == [
        "upfront_user_intent_planning",
        "upfront_worker_call_selection",
        "upfront_worker_dag_planning",
    ]
    assert [task.worker_id for task in tasks] == ["W07", "W06"]
    assert tasks[1].dependency_task_ids == ["T01"]
    assert metadata["planner"] == "upfront_worker_dag_main_agent"
    assert metadata["canonical_intent_contract"]["needs"][-1]["need_id"] == "N_FINAL"
    assert "user_facing_report" in metadata["goal_contract"]["desired_outputs"]
    assert metadata["raw_request_semantic_owner"] == "canonical_intent_contract"


def test_worker_call_selection_cannot_omit_terminal_report() -> None:
    from agent.collaboration.planner import CoordinatorPlanner

    class FakeLLM:
        def generate_json(self, **kwargs):
            stage = kwargs["stage"]
            if stage == "upfront_user_intent_planning":
                payload = {
                    "intent_summary": "分析实体",
                    "needs": [{"description": "形成实体分析", "required": True}],
                    "constraints": [],
                    "scope_note": "单实体",
                    "effect_limit": "read",
                }
                kwargs["validator"](payload)
                return payload
            if stage == "upfront_worker_call_selection":
                payload = {
                    "worker_calls": [{
                        "call_id": "WC01",
                        "worker_id": "W09",
                        "objective": "实体分析",
                        "covers_need_ids": ["N01"],
                        "desired_output_slots": ["entity_analysis"],
                    }],
                    "selection_reason": "missing presentation on purpose",
                }
                with pytest.raises(Exception, match="terminal_user_facing_report_uncovered"):
                    kwargs["validator"](payload)
                raise RuntimeError("terminal coverage rejected")
            raise AssertionError(stage)

    with pytest.raises(RuntimeError, match="terminal coverage rejected"):
        CoordinatorPlanner(CapabilityWorkerDirectory(), llm_service=FakeLLM()).plan(
            query="分析贵州茅台", request_mode="analysis", session_id="s", run_id="r", user_id="u",
            focus_refs=[], context_refs=[], memory_summary="",
        )

def test_error_contracts_are_minimal() -> None:
    from agent.collaboration.error_contracts import WorkerEscalation
    from agent.tool_runtime import ToolError

    tool_error = ToolError.create(
        error_id="missing_required_input",
        operation="查询关系路径",
        reason="缺少target_entity_refs",
    ).to_dict()
    worker_error = WorkerEscalation.create(
        error_id="capability_not_fulfillable",
        operation="获取图关系事实",
        reason="兼容私有Tool均无法产出合同槽位",
    ).to_dict()
    assert set(tool_error) == {"error_id", "operation", "reason"}
    assert set(worker_error) == {"error_id", "operation", "reason"}



def test_worker_minimum_inputs_are_contract_owned() -> None:
    task = GraphAgentTask(
        task_id="T09", run_id="r", session_id="s", worker_id="W09",
        assigned_agent="ENTITY_ANALYST", objective="形成范围受限分析", user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "T09-C01",
            "required_inputs": [
                {"slot_id": "authoritative_entity_refs", "required": True},
                {"slot_id": "entity_external_evidence", "required": True},
                {"slot_id": "entity_model_signals", "required": False},
            ],
        }],
    )
    assert contract_required_slot_ids(task) == {
        "authoritative_entity_refs", "entity_external_evidence"
    }
    card = CapabilityWorkerDirectory().get("W09")
    assert "只处理当前CapabilityContract实际绑定" in card.full_description


def test_local_tool_replan_skips_when_required_outputs_already_frozen() -> None:
    class NoLLM:
        def generate_json(self, **kwargs):
            raise AssertionError("LLM must not be called after deterministic satisfaction")

    plan = ToolDagPlan(
        worker_task_id="T04",
        worker_role="PORTFOLIO_ANALYST",
        goal_contract={"required_output_keys": [
            "entity_model_signals", "market_ranking_signals", "model_quality_metrics"
        ]},
        tasks=[
            ToolDagTask("TT1", "a", "a"),
            ToolDagTask("TT2", "b", "b"),
            ToolDagTask("TT3", "c", "c"),
        ],
        final_output_task_ids=["TT1", "TT2", "TT3"],
    )
    records = [
        {"status": "succeeded", "execution_success": True, "contract_valid": True,
         "should_freeze": True, "produced_output_keys": ["entity_model_signals"]},
        {"status": "succeeded", "execution_success": True, "contract_valid": True,
         "should_freeze": True, "produced_output_keys": ["market_ranking_signals"]},
        {"status": "succeeded", "execution_success": True, "contract_valid": True,
         "should_freeze": True, "produced_output_keys": ["model_quality_metrics"]},
    ]
    planner = WorkerToolDagPlanner(llm_service=NoLLM(), directory=object(), validator=object())
    result = planner.replan(
        previous_plan=plan,
        node_records=records,
        reusable_results={"TT1": {}, "TT2": {}, "TT3": {}},
        available_context={}, worker_prompt="", allowed_tool_names=[], run_id="r", read_only=True,
    )
    assert result is plan


def test_entity_analysis_sees_only_contract_declared_slots() -> None:
    task = GraphAgentTask(
        task_id="T09", run_id="r", session_id="s", worker_id="W09",
        assigned_agent="ENTITY_ANALYST", objective="分析", user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "T09-C01",
            "required_inputs": [
                {"slot_id": "entity_external_evidence", "required": True},
            ],
        }],
        resolved_input_bindings=[{
            "source_type": "upstream_task", "output_slot_id": "entity_external_evidence",
            "input_slot_id": "entity_external_evidence", "producer_task_id": "T01",
            "producer_contract_id": "T01-C01",
        }],
    )
    rows = entity_resolved_items(task, {
        "entity_external_evidence": {"record_count": 0},
        "entity_model_signals": {"hidden": "must not be visible"},
        "graph_relation_facts": {"hidden": "must not be visible"},
    })
    assert [row["slot_id"] for row in rows] == ["entity_external_evidence"]
    assert contract_input_slot_ids(task) == {"entity_external_evidence"}


def test_empty_bound_slot_is_still_present() -> None:
    from agent.collaboration.workers.slot_inputs import available_slot_ids, slot_envelopes
    task = GraphAgentTask(
        task_id="T", run_id="r", session_id="s", worker_id="W09",
        assigned_agent="ENTITY_ANALYST", objective="分析", user_id="u",
        boundary_id="entity.analysis",
        contracts=[{"contract_id": "C", "required_inputs": [{"slot_id": "records", "required": True}]}],
    )
    assert available_slot_ids({"records": []}) == {"records"}
    rows = slot_envelopes(task, {"records": []}, include_slots={"records"})
    assert len(rows) == 1 and rows[0]["payload"] == []


def test_active_runtime_has_no_legacy_execution_chain() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    deleted = [
        "agent/orchestration/multi_task_executor.py",
        "agent/router.py",
        "agent/goal_planning.py",
        "agent/intent_decomposition",
        "agent/specialists/portfolio_analysis.py",
        "agent/specialists/market_intelligence.py",
    ]
    assert all(not (root / rel).exists() for rel in deleted)
    forbidden = (
        "to_legacy_dict", "legacy_public_protocol", "legacy_entity_protocol",
        "worker-completion-report.v1", "ToolDagObservation", "execute_tool_legacy_dict",
    )
    for py in (root / "agent").rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        assert not any(token in text for token in forbidden), py


def test_runtime_owns_required_input_sufficiency() -> None:
    from pathlib import Path
    from agent.collaboration.workers.slot_inputs import missing_contract_required_slot_ids

    task = GraphAgentTask(
        task_id="T", run_id="r", session_id="s", worker_id="W09",
        assigned_agent="ENTITY_ANALYST", objective="分析", user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "C",
            "required_inputs": [
                {"slot_id": "actual_input", "required": True},
                {"slot_id": "optional_input", "required": False},
            ],
        }],
    )
    assert missing_contract_required_slot_ids(task, {"actual_input": []}) == set()
    assert missing_contract_required_slot_ids(task, {"optional_input": {}}) == {"actual_input"}

    root = Path(__file__).resolve().parents[2]
    entity_source = (root / "agent/collaboration/workers/entity_analysis.py").read_text(encoding="utf-8")
    runtime_source = (root / "agent/collaboration/specialist_runtime.py").read_text(encoding="utf-8")
    assert "missing_contract_required_slot_ids" not in entity_source
    assert "contract_required_slot_ids" not in entity_source
    assert "missing_contract_required_slot_ids" in runtime_source


def test_entity_analysis_has_no_hypothetical_gap_output_contract() -> None:
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    source = (root / "agent/collaboration/workers/entity_analysis.py").read_text(encoding="utf-8")
    forbidden = (
        "optional_analysis_domains_present",
        "optional_analysis_domains_missing",
        "input_diagnostics",
        "本次未纳入内部模型",
        "内部模型、排名或质量指标Slot",
    )
    assert not any(token in source for token in forbidden)
