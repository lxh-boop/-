from __future__ import annotations

import pytest

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import CoordinatorPlanner, CoordinatorPlanningError
from agent.graph.contracts import GraphNodeKind, GraphRef


class _FakeLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def generate_json(self, *, validator=None, **_: object) -> dict:
        if validator:
            validator(self.payload)
        return self.payload


def _focus_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )


def _run(payload: dict):
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=_FakeLLM(payload))
    return planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="session-1",
        run_id="agent_run_test",
        user_id="cht",
        focus_refs=[_focus_ref()],
        context_refs=[],
        memory_summary="",
        language="zh",
    )


def _minimal_plan_with_misplaced_runtime_arg() -> dict:
    return {
        "tasks": [
            {
                "task_id": "W01_001",
                "worker_id": "W01",
                "objective": "形成指定金融实体的结构化研究结果",
                "task_type": "retrieve_evidence",
                "args": {
                    "research_question": "分析当前表现和风险因素",
                },
                "inputs": {
                    "focus_ref_ids": ["cn:security:sse:600519"],
                },
                "constraints": ["read_only"],
                "expected_output_type": "EntityResearchResult",
                "priority": 1,
            },
            {
                "task_id": "W06_001",
                "worker_id": "W06",
                "objective": "依据上游研究结果形成最终报告",
                "task_type": "write_report",
                "args": {
                    "report_goal": "形成用户可读的分析报告",
                },
                "inputs": {
                    "upstream_results": {
                        "from_task_id": "W01_001",
                        "expected_output_type": "EntityResearchResult",
                    }
                },
                "constraints": ["upstream_results_only"],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ]
    }


def test_authoritative_runtime_args_are_bound_by_code() -> None:
    tasks, metadata = _run(_minimal_plan_with_misplaced_runtime_arg())

    evidence, report = tasks
    assert evidence.args["focus_ref_ids"] == ["cn:security:sse:600519"]
    assert evidence.inputs == {}
    assert report.args["reply_language"] == "zh"
    assert report.dependency_task_ids == ["W01_001"]
    assert metadata["dependency_derivation"] == "compiled_from_semantic_inputs"


def test_public_worker_card_marks_runtime_bound_args() -> None:
    cards = {item["worker_id"]: item for item in AgentDirectory().safe_catalog()}

    assert cards["W01"]["runtime_bound_args"] == ["focus_ref_ids"]
    assert "focus_ref_ids" not in cards["W01"]["args_schema"]["required"]
    assert cards["W06"]["runtime_bound_args"] == ["reply_language"]
    assert "reply_language" not in cards["W06"]["args_schema"]["required"]


def test_non_runtime_raw_input_value_is_rejected() -> None:
    payload = _minimal_plan_with_misplaced_runtime_arg()
    payload["tasks"][1]["inputs"]["upstream_results"] = ["W01_001"]

    with pytest.raises(CoordinatorPlanningError, match="no_anyof_schema_matched"):
        _run(payload)


def test_real_candidate_advances_past_focus_ref_binding_to_type_validation() -> None:
    payload = _minimal_plan_with_misplaced_runtime_arg()
    payload["tasks"] = [
        payload["tasks"][0],
        {
            "task_id": "T02",
            "worker_id": "W03",
            "objective": "分析实体对组合的影响路径",
            "task_type": "analyze_graph_impact",
            "args": {"analysis_question": "分析影响"},
            "inputs": {
                "source_analysis": {
                    "from_task_id": "W01_001",
                    "expected_output_type": "EntityResearchResult",
                },
                "target_state": {
                    "from_task_id": "T04",
                    "expected_output_type": "PortfolioAnalysisResult",
                },
            },
            "constraints": [],
            "expected_output_type": "ImpactAnalysisResult",
            "priority": 2,
        },
        {
            "task_id": "T04",
            "worker_id": "W06",
            "objective": "生成最终报告",
            "task_type": "write_report",
            "args": {"report_goal": "生成报告"},
            "inputs": {
                "upstream_results": {
                    "from_task_id": "T02",
                    "expected_output_type": "ImpactAnalysisResult",
                }
            },
            "constraints": [],
            "expected_output_type": "FinalReport",
            "priority": 3,
        },
    ]

    with pytest.raises(
        CoordinatorPlanningError,
        match="upstream_input_output_type_mismatch",
    ):
        _run(payload)
