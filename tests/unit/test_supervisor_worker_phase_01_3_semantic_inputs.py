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
        node_id="object:security:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
    )


def _plan() -> dict:
    return {
        "tasks": [
            {
                "task_id": "W01_001",
                "worker_id": "W01",
                "objective": "形成指定金融实体的结构化研究结果",
                "task_type": "analyze_entity_evidence",
                "args": {
                    "focus_ref_ids": ["object:security:600519"],
                    "research_question": "分析当前表现和风险因素",
                },
                "inputs": {},
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
                    "reply_language": "zh",
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


def _run(payload: dict):
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=_FakeLLM(payload))
    return planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="session-1",
        run_id="run-1",
        user_id="cht",
        focus_refs=[_focus_ref()],
        context_refs=[],
        memory_summary="",
        language="zh",
    )


def test_dependency_ids_are_compiled_from_semantic_inputs() -> None:
    tasks, metadata = _run(_plan())

    report = tasks[1]
    assert report.inputs == {
        "upstream_results": [
            {
                "from_task_id": "W01_001",
                "expected_output_type": "EntityResearchResult",
            }
        ]
    }
    assert report.dependency_task_ids == ["W01_001"]
    assert report.args == {
        "report_goal": "形成用户可读的分析报告",
        "reply_language": "zh",
    }
    assert metadata["dependency_derivation"] == "compiled_from_semantic_inputs"


def test_llm_generated_dependency_field_is_rejected() -> None:
    payload = _plan()
    payload["tasks"][1]["dependency_task_ids"] = ["W01_001"]

    with pytest.raises(CoordinatorPlanningError, match="additional_property_not_allowed"):
        _run(payload)


def test_input_role_output_contract_is_validated() -> None:
    payload = _plan()
    payload["tasks"][1]["inputs"] = {
        "upstream_results": {
            "from_task_id": "W01_001",
            "expected_output_type": "PortfolioAnalysisResult",
        }
    }

    with pytest.raises(
        CoordinatorPlanningError,
        match="upstream_input_output_type_mismatch",
    ):
        _run(payload)


def test_unknown_semantic_input_role_is_rejected() -> None:
    payload = _plan()
    payload["tasks"][1]["inputs"] = {
        "invented_role": {
            "from_task_id": "W01_001",
            "expected_output_type": "EntityResearchResult",
        }
    }

    with pytest.raises(CoordinatorPlanningError, match="unknown_upstream_input_role"):
        _run(payload)
