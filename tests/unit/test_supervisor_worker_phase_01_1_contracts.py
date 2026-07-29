from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.collaboration.agent_directory import AgentDirectory, EVIDENCE_RETRIEVER
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.planner import CoordinatorPlanner, CoordinatorPlanningError
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.worker_tools import WorkerToolDirectory, build_worker_tool_registry


def _ref(node_id: str = "object:security:600519") -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id=node_id,
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )


class FakeLLMService:
    def __init__(self, payload):
        self.payload = payload
        self.messages = []

    def generate_json(self, *, messages, validator=None, **_kwargs):
        self.messages = messages
        payload = self.payload
        if validator:
            validator(payload)
        return payload


def _simple_plan():
    return {
        "tasks": [
            {
                "task_id": "task_1",
                "worker_id": "W01",
                "objective": "围绕已确认金融实体形成独立研究结果",
                "task_type": "analyze_entity_evidence",
                "args": {
                    "focus_ref_ids": ["object:security:600519"],
                    "research_question": "分析当前表现、证据和风险因素",
                },
                "inputs": {},
                "constraints": ["read_only"],
                "expected_output_type": "EntityResearchResult",
                "priority": 1,
            },
            {
                "task_id": "task_2",
                "worker_id": "W06",
                "objective": "依据上游结构化结果形成最终用户报告",
                "task_type": "write_report",
                "args": {
                    "report_goal": "形成金融实体分析报告",
                    "reply_language": "zh",
                },
                "inputs": {
                    "upstream_results": {
                        "from_task_id": "task_1",
                        "expected_output_type": "EntityResearchResult",
                    }
                },
                "constraints": ["upstream_results_only"],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ]
    }


def test_worker_cards_are_structured_and_hide_private_tool_contracts() -> None:
    directory = AgentDirectory()
    catalog = directory.safe_catalog()
    w01 = next(item for item in catalog if item["worker_id"] == "W01")

    assert w01["agent_id"] == EVIDENCE_RETRIEVER
    assert w01["input_schema"]["required"] == ["research_question"]
    assert w01["runtime_bound_args"] == ["focus_ref_ids"]
    assert w01["input_schema"]["x-runtime-bound-args"] == ["focus_ref_ids"]
    assert w01["output_types"] == ["EntityResearchResult"]
    assert "non_responsibilities" in w01
    assert "upstream_input_bindings" in w01
    assert "dependency_arg_fields" not in w01
    assert "private_tool_ids" not in w01
    assert "private_worker_prompt" not in w01


def test_main_agent_generates_structured_worker_dag_with_worker_ids() -> None:
    service = FakeLLMService(_simple_plan())
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=service)

    tasks, metadata = planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="session-1",
        run_id="run-1",
        user_id="user-1",
        focus_refs=[_ref()],
        context_refs=[],
        memory_summary="",
        language="zh",
    )

    assert [task.worker_id for task in tasks] == ["W01", "W06"]
    assert [task.assigned_agent for task in tasks] == [
        "EVIDENCE_RETRIEVER",
        "REPORT_WRITER",
    ]
    assert tasks[0].args["focus_ref_ids"] == ["object:security:600519"]
    assert tasks[1].input_task_ids("upstream_results") == ["task_1"]
    assert tasks[1].dependency_task_ids == ["task_1"]
    assert "input_task_ids" not in tasks[1].args
    assert metadata["dependency_derivation"] == "compiled_from_semantic_inputs"
    assert metadata["worker_selection_owner"] == "main_agent"
    assert metadata["dag_mutation_after_planning"] == "forbidden"
    assert "worker_capability_catalog" in service.messages[1]["content"]


def test_analysis_plan_cannot_select_proposal_worker() -> None:
    payload = _simple_plan()
    payload["tasks"].insert(
        1,
        {
            "task_id": "task_proposal",
            "worker_id": "W05",
            "objective": "生成状态调整预案",
            "task_type": "build_proposal",
            "args": {
                "change_intent": "调整当前状态",
            },
            "inputs": {
                "current_state": {
                    "from_task_id": "task_1",
                    "expected_output_type": "EntityResearchResult",
                }
            },
            "constraints": [],
            "expected_output_type": "ReviewedProposal",
            "priority": 2,
        },
    )
    payload["tasks"][-1]["inputs"]["upstream_results"] = [
        payload["tasks"][-1]["inputs"]["upstream_results"],
        {
            "from_task_id": "task_proposal",
            "expected_output_type": "ReviewedProposal",
        },
    ]

    planner = CoordinatorPlanner(
        AgentDirectory(),
        llm_service=FakeLLMService(payload),
    )
    with pytest.raises(
        CoordinatorPlanningError,
        match="proposal_worker_not_allowed_in_read_only_mode",
    ):
        planner.plan(
            query="分析600519",
            request_mode="analysis",
            session_id="session-1",
            run_id="run-1",
            user_id="user-1",
            focus_refs=[_ref()],
            context_refs=[],
            memory_summary="",
        )


def test_graph_impact_contract_requires_declared_upstream_output_types() -> None:
    payload = _simple_plan()
    payload["tasks"].insert(
        1,
        {
            "task_id": "task_impact",
            "worker_id": "W03",
            "objective": "分析源结果到目标状态的影响路径",
            "task_type": "analyze_graph_impact",
            "args": {
                "analysis_question": "分析影响路径",
            },
            "inputs": {
                "source_analysis": {
                    "from_task_id": "task_1",
                    "expected_output_type": "EntityResearchResult",
                },
                "target_state": {
                    "from_task_id": "task_1",
                    "expected_output_type": "EntityResearchResult",
                },
            },
            "constraints": [],
            "expected_output_type": "ImpactAnalysisResult",
            "priority": 2,
        },
    )
    payload["tasks"][-1]["inputs"]["upstream_results"] = [
        payload["tasks"][-1]["inputs"]["upstream_results"],
        {
            "from_task_id": "task_impact",
            "expected_output_type": "ImpactAnalysisResult",
        },
    ]

    planner = CoordinatorPlanner(
        AgentDirectory(),
        llm_service=FakeLLMService(payload),
    )
    with pytest.raises(
        CoordinatorPlanningError,
        match="upstream_input_output_type_not_accepted",
    ):
        planner.plan(
            query="分析影响",
            request_mode="analysis",
            session_id="session-1",
            run_id="run-1",
            user_id="user-1",
            focus_refs=[_ref()],
            context_refs=[],
            memory_summary="",
        )


def test_llm_cannot_supply_derived_dependency_field() -> None:
    payload = _simple_plan()
    payload["tasks"][1]["dependency_task_ids"] = ["task_1"]
    planner = CoordinatorPlanner(
        AgentDirectory(),
        llm_service=FakeLLMService(payload),
    )
    with pytest.raises(
        CoordinatorPlanningError,
        match="additional_property_not_allowed",
    ):
        planner.plan(
            query="分析600519",
            request_mode="analysis",
            session_id="session-1",
            run_id="run-1",
            user_id="user-1",
            focus_refs=[_ref()],
            context_refs=[],
            memory_summary="",
        )


def test_runtime_contract_requires_dependencies_to_match_semantic_inputs() -> None:
    directory = AgentDirectory()
    task = GraphAgentTask(
        task_id="task_report",
        run_id="run-1",
        session_id="session-1",
        assigned_agent="REPORT_WRITER",
        worker_id="W06",
        objective="形成最终报告",
        task_type="write_report",
        user_id="user-1",
        args={"report_goal": "形成报告", "reply_language": "zh"},
        inputs={
            "upstream_results": {
                "from_task_id": "task_1",
                "expected_output_type": "EntityResearchResult",
            }
        },
        dependency_task_ids=[],
        expected_output_type="FinalReport",
    )
    with pytest.raises(WorkerContractViolation, match="derived_dependency_mismatch"):
        directory.validate_task_contract(task)


def test_worker_result_output_schema_is_machine_validated() -> None:
    directory = AgentDirectory()
    valid = GraphWorkerResult(
        task_id="task_1",
        agent_id="EVIDENCE_RETRIEVER",
        status=ResultStatus.COMPLETED,
        output_type="EntityResearchResult",
        data={
            "entity_refs": [_ref().to_dict()],
            "research_question": "分析当前表现",
            "results": [],
            "evidence_refs": [],
            "conclusion": "完成",
        },
        summary="完成",
    )
    directory.validate_result(valid)

    invalid = GraphWorkerResult(
        task_id="task_1",
        agent_id="EVIDENCE_RETRIEVER",
        status=ResultStatus.COMPLETED,
        output_type="PortfolioAnalysisResult",
        data={},
        summary="错误输出类型",
    )
    with pytest.raises(
        WorkerContractViolation,
        match="undeclared_worker_output_type",
    ):
        directory.validate_result(invalid)


def test_private_tool_catalog_contains_tool_schemas_only_for_worker_runtime() -> None:
    provider = SimpleNamespace()
    # Tool handlers capture provider methods but are not executed in this test.
    registry = build_worker_tool_registry(provider=provider)
    directory = WorkerToolDirectory(registry)
    catalog = directory.private_catalog(EVIDENCE_RETRIEVER)

    assert {item["tool_id"] for item in catalog} == {
        "graph.evidence.analyze_entities",
        "graph.evidence.retrieve",
    }
    assert all("input_schema" in item for item in catalog)
    assert all("output_schema" in item for item in catalog)
