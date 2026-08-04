from __future__ import annotations

import json
from types import SimpleNamespace

from agent.collaboration.agent_directory import AgentDirectory, ENTITY_ANALYST
from agent.collaboration.completion import (
    COMPLETION_REPORT_VERSION,
    flow_decision,
    validate_completion_report,
)
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.tool_dag.contracts import TOOL_DAG_OUTPUT_SCHEMA


def _ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        source="test",
        locked=True,
    )


def _task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T02",
        run_id="run-v17",
        session_id="session-v17",
        worker_id="W09",
        assigned_agent=ENTITY_ANALYST,
        objective="分析贵州茅台",
        task_type="analyze_financial_entities",
        args={"analysis_goal": "分析贵州茅台"},
        expected_output_type="EntityAnalysisResult",
        expected_output={
            "information_slots": ["entity_analysis", "entity_analysis_uncertainty"]
        },
        user_id="u",
        focus_refs=[_ref()],
    )


def _dependencies() -> dict[str, dict]:
    return {
        "T01": {
            "contract_version": "graph_worker_result.v1",
            "task_id": "T01",
            "agent_id": "EVIDENCE_COLLECTOR",
            "status": "completed",
            "output_type": "EvidenceCollectionResult",
            "payload": {
                "entity_refs": [_ref().to_dict()],
                "entity_catalog": [
                    {
                        "node_id": _ref().node_id,
                        "public_code": "600519",
                        "display_label": "贵州茅台",
                    }
                ],
                "collection_goal": "收集证据",
                "results": [],
                "record_count": 0,
                "source_count": 0,
                "deduplication": {
                    "raw_record_count": 0,
                    "canonical_record_count": 0,
                    "duplicate_record_count": 0,
                },
                "coverage": {"coverage_satisfied": True},
                "business_empty": True,
                "write_performed": False,
            },
            "summary": "证据查询完成，业务结果为空。",
            "confidence": 1.0,
        },
        "T00": {
            "contract_version": "graph_worker_result.v1",
            "task_id": "T00",
            "agent_id": "PORTFOLIO_ANALYST",
            "status": "completed",
            "output_type": "ModelPredictionResult",
            "payload": {
                "security_ref": _ref().to_dict(),
                "found": True,
                "record": {"score": 0.71, "predicted_return": 0.02},
                "data_date": "2026-08-01",
                "rank": 12,
                "is_topk": False,
                "total_count": 300,
                "source_id": "model:test",
                "reason": "test internal signal",
            },
            "summary": "系统内部模型事实已返回。",
            "confidence": 1.0,
        },
    }



class _Provider:
    def provider_symbol(self, ref: GraphRef) -> str:
        return "600519"


class _EntityCompletionLLM:
    def __init__(self, *, completed: bool) -> None:
        self.completed = completed

    def generate_json(self, **kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        contract = request["completion_contract"]
        produced = (
            list(contract["required_information_slots"])
            if self.completed
            else ["entity_analysis_uncertainty"]
        )
        missing = [
            item
            for item in contract["required_information_slots"]
            if item not in produced
        ]
        criteria = [
            {
                "criterion_id": item["criterion_id"],
                "satisfied": bool(self.completed),
                "reason": "结构化上游结果支持该判断。" if self.completed else "未形成有效实体分析。",
                "source_refs": ["T01", "T00"] if self.completed else [],
            }
            for item in contract["criteria"]
        ]
        payload = {
            "entity_refs": [_ref().to_dict()],
            "facts": ([{"claim_id": "F01", "statement": "证据查询为空。", "source_task_ids": ["T01"]}] if self.completed else []),
            "analysis": ([{"claim_id": "A01", "statement": "当前只能确认指定范围内未检索到证据。", "source_task_ids": ["T01"]}] if self.completed else []),
            "model_signals": ([{
                "claim_id": "M01",
                "statement": "系统内部模型评分为0.71。",
                "source_task_ids": ["T00"],
                "direction": "up",
                "horizon": "next_5_trading_days",
                "strength": "moderate",
            }] if self.completed else []),
            "relation_interpretations": [],
            "uncertainties": [
                {
                    "claim_id": "U01",
                    "statement": "缺少足够证据，不能形成进一步分析。",
                    "source_task_ids": ["T01", "T00"],
                }
            ],
            "conclusion": "已完成空结果分析。" if self.completed else "未完成实体分析。",
            "source_task_ids": ["T01", "T00"],
            "completion_report": {
                "schema_version": COMPLETION_REPORT_VERSION,
                "report_source": "llm",
                "execution_status": "succeeded",
                "contract_status": "valid",
                "business_status": "empty" if self.completed else "insufficient",
                "completion_status": "completed" if self.completed else "partially_completed",
                "expected_task_completed": self.completed,
                "output_type": "EntityAnalysisResult",
                "produced_information_slots": produced,
                "missing_information_slots": missing,
                "criteria": criteria,
                "limitations": [] if self.completed else ["未形成有效实体分析。"],
                "failure_kind": "none" if self.completed else "business_result_insufficient",
            },
        }
        validator = kwargs.get("validator")
        if validator:
            validator(payload)
        return payload


def _run_w09(completed: bool, tmp_path):
    runtime = SpecialistRuntime(
        llm_service=_EntityCompletionLLM(completed=completed),
        provider=_Provider(),
        impact_service=SimpleNamespace(),
    )
    return runtime.run(
        _task(),
        current_user_request="分析贵州茅台",
        dependency_results=_dependencies(),
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
    )


def test_required_result_fields_are_compiled_from_registered_schema() -> None:
    task = _task()
    contract = AgentDirectory().completion_contract_for_task(task)
    assert contract["required_result_fields"] == [
        "data.entity_refs",
        "data.facts",
        "data.analysis",
        "data.model_signals",
        "data.relation_interpretations",
        "data.uncertainties",
        "data.conclusion",
        "data.source_task_ids",
        "data.input_diagnostics",
    ]
    assert contract["required_information_slots"] == [
        "entity_analysis",
        "entity_analysis_uncertainty",
    ]


def test_program_routes_validated_completion_report_without_business_inference() -> None:
    task = _task()
    contract = AgentDirectory().completion_contract_for_task(task)
    report = {
        "schema_version": COMPLETION_REPORT_VERSION,
        "report_source": "llm",
        "execution_status": "succeeded",
        "contract_status": "valid",
        "business_status": "insufficient",
        "completion_status": "partially_completed",
        "expected_task_completed": False,
        "output_type": "EntityAnalysisResult",
        "produced_information_slots": ["entity_analysis_uncertainty"],
        "missing_information_slots": ["entity_analysis"],
        "criteria": [
            {
                "criterion_id": item["criterion_id"],
                "satisfied": False,
                "reason": "Worker reports the criterion is not satisfied.",
                "source_refs": [],
            }
            for item in contract["criteria"]
        ],
        "limitations": ["insufficient evidence"],
        "failure_kind": "business_result_insufficient",
    }
    validate_completion_report(report, contract)
    decision = flow_decision(
        ResultStatus.COMPLETED,
        report,
        output_type="EntityAnalysisResult",
        retryable=False,
    )
    assert decision.result_status == ResultStatus.PARTIAL
    assert decision.semantic_satisfied is False
    assert decision.replan_recommended is True


def test_w09_is_partial_when_structured_completion_report_says_not_completed(tmp_path) -> None:
    result = _run_w09(False, tmp_path)
    assert result.status == ResultStatus.PARTIAL
    assert result.completion["expected_task_completed"] is False
    assert result.metadata["semantic_satisfied"] is False
    assert result.metadata["replan_recommended"] is True


def test_w09_completed_requires_structured_completed_report(tmp_path) -> None:
    result = _run_w09(True, tmp_path)
    assert result.status == ResultStatus.COMPLETED
    assert result.completion["expected_task_completed"] is True
    assert result.metadata["semantic_satisfied"] is True
    assert result.metadata["should_freeze"] is True


def test_downstream_does_not_unlock_on_raw_completed_status_without_completed_report() -> None:
    result = GraphWorkerResult(
        task_id="T02",
        agent_id=ENTITY_ANALYST,
        status=ResultStatus.COMPLETED,
        output_type="EntityAnalysisResult",
        data={},
        completion={
            "expected_task_completed": False,
            "completion_status": "partially_completed",
        },
    )
    assert AgentCollaborationCoordinator._worker_result_usable(result) is False


def test_tool_dag_llm_schema_does_not_expose_program_owned_goal_or_output_keys() -> None:
    task_properties = TOOL_DAG_OUTPUT_SCHEMA["properties"]["tasks"]["items"]["properties"]
    root_properties = TOOL_DAG_OUTPUT_SCHEMA["properties"]
    assert "goal_contract" not in root_properties
    assert "expected_output_keys" not in task_properties
