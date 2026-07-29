from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from agent.collaboration.agent_directory import (
    AgentDirectory,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    W02,
    W06,
)
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.workers.report_writer import run_report_writer
from agent.graph.contracts import GraphNodeKind, GraphRef


def _security_ref(code: str = "600519") -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id=f"cn:security:sse:{code}",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        confidence=1.0,
        locked=True,
    )


def test_w02_public_catalog_exposes_task_contracts_but_not_private_tools() -> None:
    card = AgentDirectory().get(W02)
    public = card.safe_for_coordinator()
    by_type = {item["task_type"]: item for item in public["task_contracts"]}

    assert public["role"] == "INTERNAL_SYSTEM_RETRIEVER"
    assert by_type["query_stock_prediction"]["output_type"] == "ModelPredictionResult"
    assert by_type["query_portfolio_state"]["output_type"] == "PortfolioAnalysisResult"
    prediction = by_type["query_stock_prediction"]
    assert prediction["runtime_bound_args"] == ["focus_ref_ids"]
    assert "input_schema" not in prediction
    assert prediction["args_schema"]["properties"]["top_k"]["default"] == 10
    assert prediction["default_args"] == {"top_k": 10}
    assert prediction["semantic_inputs_schema"]["properties"] == {}
    assert "private_tool_ids" not in str(public)


def test_w02_stock_prediction_reads_existing_ranking_and_returns_typed_payload(tmp_path) -> None:
    pd.DataFrame(
        [
            {
                "rank": 1,
                "date": "2026-07-28",
                "code": "600519",
                "name": "贵州茅台",
                "pred_5d_ret": 0.023,
                "up_prob": 0.64,
                "score": 0.71,
                "confidence": 0.76,
                "risk_level": "medium",
                "model_name": "StockRouter",
            }
        ]
    ).to_csv(tmp_path / "ranking_latest.csv", index=False, encoding="utf-8-sig")
    ref = _security_ref()
    task = GraphAgentTask(
        task_id="W02_001",
        run_id="run-1",
        session_id="session-1",
        worker_id=W02,
        assigned_agent=PORTFOLIO_ANALYST,
        objective="查询该证券的模型预测",
        task_type="query_stock_prediction",
        user_id="cht",
        args={"focus_ref_ids": [ref.node_id], "top_k": 10},
        expected_output_type="ModelPredictionResult",
        focus_refs=[ref],
        dependency_task_ids=[],
        metadata={"structured_worker_contract": True},
    )
    runtime = SpecialistRuntime(
        llm_service=SimpleNamespace(),
        provider=SimpleNamespace(),
        impact_service=SimpleNamespace(),
    )

    result = runtime.run(
        task,
        current_user_request="分析600519",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
    )

    assert result.status == ResultStatus.COMPLETED
    assert result.output_type == "ModelPredictionResult"
    assert result.payload_schema == "ModelPredictionResult.v1"
    assert result.payload["found"] is True
    assert result.payload["rank"] == 1
    assert result.payload["is_topk"] is True
    assert result.payload["record"]["model_name"] == "StockRouter"
    assert result.payload["security_ref"]["node_id"] == ref.node_id


def test_task_specific_contract_rejects_wrong_w02_output_type() -> None:
    directory = AgentDirectory()
    task = GraphAgentTask(
        task_id="W02_001",
        run_id="run-1",
        session_id="session-1",
        worker_id=W02,
        assigned_agent=PORTFOLIO_ANALYST,
        objective="查询模型预测",
        task_type="query_stock_prediction",
        user_id="cht",
        args={"focus_ref_ids": ["cn:security:sse:600519"]},
        expected_output_type="PortfolioAnalysisResult",
        focus_refs=[_security_ref()],
        dependency_task_ids=[],
    )

    with pytest.raises(WorkerContractViolation, match="task_contract_output_type_mismatch"):
        directory.validate_task_contract(task)


def test_explicit_input_binder_uses_role_task_and_expected_type() -> None:
    directory = AgentDirectory()
    task = GraphAgentTask(
        task_id="W06_001",
        run_id="run-1",
        session_id="session-1",
        worker_id=W06,
        assigned_agent=REPORT_WRITER,
        objective="生成报告",
        task_type="write_report",
        user_id="cht",
        args={"report_goal": "分析600519", "reply_language": "zh"},
        inputs={
            "upstream_results": [
                {
                    "from_task_id": "W02_001",
                    "expected_output_type": "ModelPredictionResult",
                }
            ]
        },
        expected_output_type="FinalReport",
        dependency_task_ids=["W02_001"],
    )
    dependencies = {
        "W02_001": GraphWorkerResult(
            task_id="W02_001",
            agent_id=PORTFOLIO_ANALYST,
            status=ResultStatus.COMPLETED,
            output_type="ModelPredictionResult",
            payload_schema="model_prediction_result.v1",
            payload={"rank": 1, "score": 0.71},
            data={"rank": 1, "score": 0.71},
            summary="模型预测已读取",
        ).safe_for_coordinator()
    }

    resolved = directory.resolve_task_inputs(task, dependencies)

    item = resolved["upstream_results"][0]
    assert item["from_task_id"] == "W02_001"
    assert item["output_type"] == "ModelPredictionResult"
    assert item["payload"] == {"rank": 1, "score": 0.71}


def test_report_writer_receives_resolved_typed_payload_not_ambiguous_findings() -> None:
    llm = SimpleNamespace(generate_text=Mock(return_value="模型排名第1，并结合外部证据形成结论。"))
    task = GraphAgentTask(
        task_id="W06_001",
        run_id="run-1",
        session_id="session-1",
        worker_id=W06,
        assigned_agent=REPORT_WRITER,
        objective="生成综合报告",
        task_type="write_report",
        user_id="cht",
        args={"report_goal": "分析600519", "reply_language": "zh"},
        inputs={
            "upstream_results": [
                {"from_task_id": "W02_001", "expected_output_type": "ModelPredictionResult"}
            ]
        },
        expected_output_type="FinalReport",
        dependency_task_ids=["W02_001"],
    )
    resolved_inputs = {
        "upstream_results": [
            {
                "from_task_id": "W02_001",
                "status": "completed",
                "output_type": "ModelPredictionResult",
                "payload_schema": "model_prediction_result.v1",
                "payload_version": "v1",
                "payload": {"rank": 1, "score": 0.71},
                "summary": "模型预测已读取",
                "evidence_refs": [],
                "artifact_refs": [],
            }
        ]
    }

    result = run_report_writer(
        llm,
        task,
        {"W02_001": {"findings": [{"score": "ambiguous"}]}},
        "zh",
        resolved_inputs=resolved_inputs,
    )

    sent = llm.generate_text.call_args.kwargs["messages"][1]["content"]
    assert '"payload": {"rank": 1, "score": 0.71}' in sent
    assert "ambiguous" not in sent
    assert result.status == ResultStatus.COMPLETED


def test_planner_compiles_comprehensive_stock_analysis_w01_w02_w06_without_new_edges() -> None:
    directory = AgentDirectory()
    planner = CoordinatorPlanner(directory, llm_service=SimpleNamespace())
    payload = {
        "tasks": [
            {
                "task_id": "W01_001",
                "worker_id": "W01",
                "objective": "研究该金融实体的外部证据",
                "task_type": "retrieve_evidence",
                "args": {"research_question": "分析公司与市场证据"},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "EntityResearchResult",
                "priority": 1,
            },
            {
                "task_id": "W02_001",
                "worker_id": "W02",
                "objective": "查询该证券的内部模型预测",
                "task_type": "query_stock_prediction",
                "args": {"top_k": 10},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "ModelPredictionResult",
                "priority": 1,
            },
            {
                "task_id": "W06_001",
                "worker_id": "W06",
                "objective": "汇总外部证据与内部模型结果",
                "task_type": "write_report",
                "args": {"report_goal": "分析600519"},
                "inputs": {
                    "upstream_results": [
                        {"from_task_id": "W01_001", "expected_output_type": "EntityResearchResult"},
                        {"from_task_id": "W02_001", "expected_output_type": "ModelPredictionResult"},
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ]
    }
    prepared, audit = planner._prepare_payload(
        payload,
        runtime_values={
            "focus_ref_ids": ["cn:security:sse:600519"],
            "context_ref_ids": [],
            "all_ref_ids": ["cn:security:sse:600519"],
            "user_id": "cht",
            "reply_language": "zh",
            "as_of_time": "",
            "run_id": "run-1",
        },
    )
    planner._validate_payload(
        prepared,
        request_mode="analysis",
        authoritative_ref_ids={"cn:security:sse:600519"},
        authoritative_user_id="cht",
        reply_language="zh",
    )
    compiled = planner._compile_payload(prepared)
    by_id = {row["task_id"]: row for row in compiled["tasks"]}

    assert by_id["W01_001"]["args"]["focus_ref_ids"] == ["cn:security:sse:600519"]
    assert by_id["W02_001"]["args"]["focus_ref_ids"] == ["cn:security:sse:600519"]
    assert by_id["W01_001"]["dependency_task_ids"] == []
    assert by_id["W02_001"]["dependency_task_ids"] == []
    assert by_id["W06_001"]["dependency_task_ids"] == ["W01_001", "W02_001"]
    assert {item["task_id"] for item in audit["tasks"]} == {"W01_001", "W02_001", "W06_001"}
