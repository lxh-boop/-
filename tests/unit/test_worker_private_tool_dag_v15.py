from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.collaboration.agent_directory import AgentDirectory, EVIDENCE_COLLECTOR, W01
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.services.evidence_service import EvidenceService
from agent.tool_dag import ToolDagValidator
from agent.worker_tools import (
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    EVIDENCE_SEARCH_NEWS_TOOL,
    EVIDENCE_SEARCH_RAG_TOOL,
    WorkerToolDirectory,
    build_worker_tool_registry,
)


def _ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        source="test",
        locked=True,
    )


class _Provider:
    def provider_symbol(self, ref: GraphRef) -> str:
        assert ref.node_id == "cn:security:sse:600519"
        return "600519"


class _ToolDagLLM:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def generate_json(self, **kwargs):
        self.operations.append(str(kwargs.get("operation") or ""))
        payload = {
            "goal_contract": {
                "goal_summary": "收集实体集合的外部证据",
                "required_output_keys": [
                    "validated_evidence_collection",
                    "results",
                    "record_count",
                    "source_count",
                    "coverage",
                ],
                "completion_criteria": ["完成来源读取、去重和覆盖校验"],
            },
            "tasks": [
                {
                    "tool_task_id": "TT1",
                    "tool_name": EVIDENCE_SEARCH_NEWS_TOOL,
                    "objective": "读取新闻和公告证据",
                    "args": {},
                    "inputs": {
                        "object_refs": {"from_context": "object_refs"},
                        "top_k": {"from_context": "top_k"},
                        "as_of_time": {"from_context": "as_of_time"},
                    },
                    "expected_output_keys": ["results"],
                    "priority": 1,
                },
                {
                    "tool_task_id": "TT2",
                    "tool_name": EVIDENCE_SEARCH_RAG_TOOL,
                    "objective": "读取RAG证据",
                    "args": {},
                    "inputs": {
                        "object_refs": {"from_context": "object_refs"},
                        "query": {"from_context": "query"},
                        "top_k": {"from_context": "top_k"},
                        "as_of_time": {"from_context": "as_of_time"},
                    },
                    "expected_output_keys": ["results"],
                    "priority": 1,
                },
                {
                    "tool_task_id": "TT3",
                    "tool_name": EVIDENCE_FINALIZE_COLLECTION_TOOL,
                    "objective": "合并并验证证据集合",
                    "args": {},
                    "inputs": {
                        "collections": [
                            {"from_tool_task_id": "TT1"},
                            {"from_tool_task_id": "TT2"},
                        ],
                        "required_object_refs": {"from_context": "required_object_refs"},
                        "collection_goal": {"from_context": "collection_goal"},
                    },
                    "expected_output_keys": [
                        "validated_evidence_collection",
                        "results",
                        "record_count",
                        "source_count",
                        "coverage",
                    ],
                    "priority": 2,
                },
            ],
            "final_output_task_ids": ["TT3"],
        }
        validator = kwargs.get("validator")
        if validator:
            validator(payload)
        return payload


def test_w01_public_card_is_high_level_and_private_tools_are_hidden() -> None:
    directory = AgentDirectory()
    card = directory.get(W01)
    assert card.accepted_task_types == ["collect_external_evidence"]
    assert card.private_tools_for("collect_external_evidence") == [
        EVIDENCE_SEARCH_NEWS_TOOL,
        EVIDENCE_SEARCH_RAG_TOOL,
        EVIDENCE_FINALIZE_COLLECTION_TOOL,
    ]
    rendered = json.dumps(directory.planning_catalog(), ensure_ascii=False)
    assert EVIDENCE_SEARCH_NEWS_TOOL not in rendered
    assert EVIDENCE_SEARCH_RAG_TOOL not in rendered
    assert EVIDENCE_FINALIZE_COLLECTION_TOOL not in rendered


def test_tool_dag_validator_accepts_a_single_node_plan() -> None:
    provider = _Provider()
    registry = build_worker_tool_registry(provider=provider)
    directory = WorkerToolDirectory(registry)
    validator = ToolDagValidator(registry, directory)
    payload = {
        "goal_contract": {
            "goal_summary": "完成空结果的证据集合校验",
            "required_output_keys": ["validated_evidence_collection", "coverage"],
            "completion_criteria": ["返回校验结果"],
        },
        "tasks": [
            {
                "tool_task_id": "TT1",
                "tool_name": EVIDENCE_FINALIZE_COLLECTION_TOOL,
                "objective": "校验证据集合",
                "args": {"collections": []},
                "inputs": {
                    "required_object_refs": {"from_context": "required_object_refs"},
                    "collection_goal": {"from_context": "collection_goal"},
                },
                "expected_output_keys": ["validated_evidence_collection", "coverage"],
                "priority": 1,
            }
        ],
        "final_output_task_ids": ["TT1"],
    }
    plan = validator.validate_payload(
        payload,
        worker_role=EVIDENCE_COLLECTOR,
        worker_task_id="W01_TASK",
        available_context_keys={"required_object_refs", "collection_goal"},
        allowed_tool_names=set(AgentDirectory().get(W01).private_tools_for("collect_external_evidence")),
        read_only=True,
    )
    assert len(plan.tasks) == 1
    assert plan.final_output_task_ids == ["TT1"]


def test_w01_executes_dynamic_parallel_tool_dag(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        EvidenceService,
        "search_news",
        lambda self, code, **kwargs: {
            "success": True,
            "data": {
                "records": [{"news_id": "N1", "title": "公告", "text": "内容", "score": 0.8}],
                "sources": [{"source_id": "S1", "source_type": "announcement"}],
            },
        },
    )
    monkeypatch.setattr(
        EvidenceService,
        "search_rag",
        lambda self, code, **kwargs: {
            "success": True,
            "data": {
                "records": [{"chunk_id": "C1", "title": "研报", "text": "资料", "score": 0.7}],
                "sources": [{"source_id": "S2", "source_type": "rag"}],
            },
        },
    )
    llm = _ToolDagLLM()
    runtime = SpecialistRuntime(
        llm_service=llm,
        provider=_Provider(),
        impact_service=SimpleNamespace(),
    )
    task = GraphAgentTask(
        task_id="T01",
        run_id="run-v15",
        session_id="session-v15",
        worker_id="W01",
        assigned_agent=EVIDENCE_COLLECTOR,
        objective="收集贵州茅台外部证据",
        task_type="collect_external_evidence",
        args={
            "entity_ref_ids": [_ref().node_id],
            "collection_goal": "收集近期公告、新闻和研报",
            "top_k": 10,
        },
        expected_output_type="EvidenceCollectionResult",
        user_id="u",
        focus_refs=[_ref()],
    )
    result = runtime.run(
        task,
        current_user_request="分析贵州茅台",
        dependency_results={},
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert result.data["record_count"] == 2
    assert result.data["coverage"]["coverage_satisfied"] is True
    assert result.metadata["tool_dag_used"] is True
    assert result.metadata["tool_task_count"] == 3
    assert result.metadata["tool_dag_batch_count"] == 2
    assert llm.operations == ["worker_tool_dag_plan:EVIDENCE_COLLECTOR:collect_external_evidence"]


class _EntityLLM:
    def __init__(self, *, invalid: bool = False) -> None:
        self.invalid = invalid
        self.user_message = ""

    def generate_json(self, **kwargs):
        self.user_message = kwargs["messages"][1]["content"]
        if self.invalid:
            payload = {
                "entity_refs": [{"node_id": "cn:security:sse:600519"}],
                "facts": ["bad string"],
                "analysis": [],
                "model_signals": [],
                "relation_interpretations": [],
                "uncertainties": [],
                "conclusion": "",
                "source_task_ids": ["T01"],
            }
        else:
            payload = {
                "entity_refs": [{"node_id": "cn:security:sse:600519"}],
                "facts": [{"statement": "事实", "source_task_ids": ["T01"]}],
                "analysis": [{"statement": "分析", "source_task_ids": ["T01"]}],
                "model_signals": [],
                "relation_interpretations": [],
                "uncertainties": [{"statement": "不确定性", "source_task_ids": []}],
                "conclusion": "结论",
                "source_task_ids": ["T01"],
            }
        validator = kwargs.get("validator")
        if validator:
            validator(payload)
        return payload


def _entity_task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T09",
        run_id="run",
        session_id="session",
        worker_id="W09",
        assigned_agent="ENTITY_ANALYST",
        objective="分析贵州茅台",
        task_type="analyze_financial_entities",
        args={"analysis_goal": "分析贵州茅台"},
        inputs={"evidence": {"from_task_id": "T01", "expected_output_type": "EvidenceCollectionResult"}},
        expected_output_type="EntityAnalysisResult",
        user_id="u",
        focus_refs=[_ref()],
    )


def _large_evidence_input() -> dict:
    records = [
        {
            "chunk_id": f"C{i}",
            "title": f"标题{i}",
            "text": "长文本" * 3000,
            "score": 1 - i / 100,
        }
        for i in range(40)
    ]
    return {
        "evidence": {
            "from_task_id": "T01",
            "output_type": "EvidenceCollectionResult",
            "status": "completed",
            "payload": {
                "entity_refs": [_ref().to_dict()],
                "collection_goal": "收集证据",
                "results": [{"focus_ref": _ref().to_dict(), "records": records, "sources": []}],
                "record_count": 40,
                "source_count": 0,
                "coverage": {"coverage_satisfied": True},
            },
        }
    }


def test_w09_rejects_string_claim_items_from_uploaded_failure_shape() -> None:
    with pytest.raises(RuntimeError, match="item_must_be_object"):
        run_entity_analysis(
            _EntityLLM(invalid=True),
            _entity_task(),
            {},
            resolved_inputs=_large_evidence_input(),
            language="zh",
        )


def test_w09_compacts_large_evidence_and_returns_object_claims() -> None:
    llm = _EntityLLM()
    result = run_entity_analysis(
        llm,
        _entity_task(),
        {},
        resolved_inputs=_large_evidence_input(),
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert isinstance(result.data["facts"][0], dict)
    assert len(llm.user_message) < 30000
    decoded = json.loads(llm.user_message)
    assert len(decoded["upstream_results"][0]["payload"]["results"][0]["records"]) == 12


def test_authoritative_entity_catalog_supports_report_label_grounding() -> None:
    from agent.collaboration.report_validation import build_report_policy, validate_report_output

    llm = _EntityLLM()
    task = _entity_task()
    task.metadata["authoritative_entity_catalog"] = [
        {
            "entity_ref": _ref().to_dict(),
            "node_id": _ref().node_id,
            "public_code": "600519",
            "display_label": "贵州茅台",
            "identity_source": "identity",
            "identity_locked": True,
        }
    ]
    result = run_entity_analysis(
        llm,
        task,
        {},
        resolved_inputs=_large_evidence_input(),
        language="zh",
    )
    policy = build_report_policy("分析贵州茅台", [result.safe_for_coordinator()])
    checked = validate_report_output("# 贵州茅台（600519）分析\n\n基于上游实体分析结果。", policy)
    assert checked.valid is True
