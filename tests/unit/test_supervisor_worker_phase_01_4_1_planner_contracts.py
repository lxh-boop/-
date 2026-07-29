from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import CoordinatorPlanner, CoordinatorPlanningError
from agent.graph.contracts import GraphNodeKind, GraphRef
from core.llm.service import LLMService


def _focus_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        confidence=1.0,
        locked=True,
    )


def _runtime_values() -> dict:
    return {
        "focus_ref_ids": ["cn:security:sse:600519"],
        "context_ref_ids": [],
        "all_ref_ids": ["cn:security:sse:600519"],
        "user_id": "cht",
        "reply_language": "zh",
        "as_of_time": "",
        "run_id": "run-1",
    }


def _real_failed_candidate() -> dict:
    return {
        "tasks": [
            {
                "task_id": "W01_001",
                "worker_id": "W01",
                "objective": "围绕证券600519形成实体研究结果",
                "task_type": "analyze_entity_evidence",
                "args": {},
                "inputs": {
                    "focus_ref_ids": ["cn:security:sse:600519"],
                    "research_question": "分析市场背景、业务结构与行业地位",
                },
                "constraints": [],
                "expected_output_type": "EntityResearchResult",
                "priority": 1,
            },
            {
                "task_id": "W02_001",
                "worker_id": "W02",
                "objective": "查询证券600519的模型预测",
                "task_type": "query_stock_prediction",
                "args": {},
                "inputs": {
                    "focus_ref_ids": ["cn:security:sse:600519"],
                    "top_k": 10,
                    "model_name": "default_model",
                },
                "constraints": [],
                "expected_output_type": "ModelPredictionResult",
                "priority": 1,
            },
            {
                "task_id": "W06_001",
                "worker_id": "W06",
                "objective": "汇总实体研究与模型预测",
                "task_type": "write_report",
                "args": {"report_goal": "分析600519"},
                "inputs": {
                    "upstream_results": [
                        {
                            "from_task_id": "W01_001",
                            "expected_output_type": "EntityResearchResult",
                        },
                        {
                            "from_task_id": "W02_001",
                            "expected_output_type": "ModelPredictionResult",
                        },
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ]
    }


def _corrected_candidate(*, include_top_k: bool = False) -> dict:
    prediction_args = {"top_k": 10} if include_top_k else {}
    return {
        "tasks": [
            {
                "task_id": "W01_001",
                "worker_id": "W01",
                "objective": "围绕证券600519形成实体研究结果",
                "task_type": "analyze_entity_evidence",
                "args": {
                    "research_question": "分析市场背景、业务结构与行业地位"
                },
                "inputs": {},
                "constraints": [],
                "expected_output_type": "EntityResearchResult",
                "priority": 1,
            },
            {
                "task_id": "W02_001",
                "worker_id": "W02",
                "objective": "查询证券600519的模型预测",
                "task_type": "query_stock_prediction",
                "args": prediction_args,
                "inputs": {},
                "constraints": [],
                "expected_output_type": "ModelPredictionResult",
                "priority": 1,
            },
            {
                "task_id": "W06_001",
                "worker_id": "W06",
                "objective": "汇总实体研究与模型预测",
                "task_type": "write_report",
                "args": {"report_goal": "分析600519"},
                "inputs": {
                    "upstream_results": [
                        {
                            "from_task_id": "W01_001",
                            "expected_output_type": "EntityResearchResult",
                        },
                        {
                            "from_task_id": "W02_001",
                            "expected_output_type": "ModelPredictionResult",
                        },
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ]
    }


def test_public_worker_contract_separates_args_and_semantic_inputs() -> None:
    catalog = {item["worker_id"]: item for item in AgentDirectory().safe_catalog()}
    w01 = catalog["W01"]
    prediction = next(
        item
        for item in catalog["W02"]["task_contracts"]
        if item["task_type"] == "query_stock_prediction"
    )

    assert "input_schema" not in w01
    assert w01["args_schema"]["required"] == ["research_question"]
    assert w01["semantic_inputs_schema"]["properties"] == {}
    assert "input_schema" not in prediction
    assert prediction["args_schema"]["properties"]["top_k"]["default"] == 10
    assert prediction["default_args"] == {"top_k": 10}
    assert prediction["semantic_inputs_schema"]["properties"] == {}
    assert prediction["runtime_bound_args"] == ["focus_ref_ids"]


def test_real_failed_candidate_gets_precise_field_placement_error() -> None:
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())
    prepared, _ = planner._prepare_payload(
        _real_failed_candidate(), runtime_values=_runtime_values()
    )

    with pytest.raises(CoordinatorPlanningError) as captured:
        try:
            planner._validate_payload(
                prepared,
                request_mode="analysis",
                authoritative_ref_ids={"cn:security:sse:600519"},
                authoritative_user_id="cht",
                reply_language="zh",
            )
        except Exception as exc:
            raise CoordinatorPlanningError(str(exc)) from exc

    message = str(captured.value)
    assert "planner_field_placement_error" in message
    assert "task=W01_001;move_to_args=research_question" in message
    assert "task=W02_001;move_to_args=model_name,top_k" in message
    assert "inputs_accept_only=from_task_id+expected_output_type" in message


def test_default_top_k_10_is_applied_by_code_when_omitted() -> None:
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())
    prepared, audit = planner._prepare_payload(
        _corrected_candidate(include_top_k=False), runtime_values=_runtime_values()
    )
    by_id = {row["task_id"]: row for row in prepared["tasks"]}

    assert by_id["W02_001"]["args"]["top_k"] == 10
    audit_by_id = {row["task_id"]: row for row in audit["tasks"]}
    assert audit_by_id["W02_001"]["default_args_applied"] == {"top_k": 10}

    planner._validate_payload(
        prepared,
        request_mode="analysis",
        authoritative_ref_ids={"cn:security:sse:600519"},
        authoritative_user_id="cht",
        reply_language="zh",
    )


def test_llm_json_repair_receives_caller_contract_guidance() -> None:
    settings = SimpleNamespace(
        profile=SimpleNamespace(
            profile_id="test",
            config_hash="hash",
            provider_id="test",
            model_name="test",
            deployment_mode="local",
            endpoint_scope="test",
        ),
        is_configured=True,
        credential="",
    )
    service = LLMService(settings=settings)
    captured_messages: list[list[dict]] = []
    outputs = ['{"ok": false}', '{"ok": true}']

    def fake_generate_text(self, **kwargs):
        captured_messages.append(kwargs["messages"])
        return outputs.pop(0)

    def validator(candidate: dict) -> None:
        if candidate.get("ok") is not True:
            raise ValueError("planner_field_placement_error@$.tasks:move_to_args=research_question")

    with patch.object(LLMService, "generate_text", new=fake_generate_text):
        result = service.generate_json(
            stage="graph_coordinator_planner",
            messages=[{"role": "system", "content": "schema"}],
            max_output_tokens=100,
            validator=validator,
            repair_guidance=(
                "将 move_to_args 字段从 inputs 移到 args；"
                "inputs 只能包含 from_task_id 和 expected_output_type。"
            ),
        )

    assert result == {"ok": True}
    repair_text = captured_messages[1][-1]["content"]
    assert "planner_field_placement_error" in repair_text
    assert "本次精确修复要求" in repair_text
    assert "move_to_args" in repair_text
    assert "from_task_id" in repair_text
