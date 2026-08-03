from __future__ import annotations

from pathlib import Path

from agent.collaboration.agent_directory import (
    AgentDirectory,
    DATABASE_WRITER,
    ENTITY_ANALYST,
    EVIDENCE_COLLECTOR,
    GRAPH_RELATION_RETRIEVER,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.collaboration.workers.graph_impact import run_graph_impact
from agent.graph.contracts import GraphNodeKind, GraphPathRef, GraphRef
from agent.worker_tools import (
    DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT,
    DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT,
    EVIDENCE_COLLECT_EXTERNAL_TOOL,
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    EVIDENCE_SEARCH_NEWS_TOOL,
    EVIDENCE_SEARCH_RAG_TOOL,
)
from agent.worker_tools.registry import build_worker_tool_registry


def _ref(node_id: str, *, kind: GraphNodeKind = GraphNodeKind.OBJECT, role: str = "focus") -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id=node_id,
        node_kind=kind,
        role=role,
        source="test",
        locked=True,
    )


def test_capability_cards_are_high_level_and_atomic() -> None:
    directory = AgentDirectory()
    assert len(directory.list_cards()) == 9

    w01 = directory.get("W01")
    assert w01.agent_id == EVIDENCE_COLLECTOR
    assert w01.accepted_task_types == ["collect_external_evidence"]
    assert w01.output_types == ["EvidenceCollectionResult"]
    assert w01.side_effects == []
    assert "分析" not in w01.responsibility
    assert w01.task_contracts[0].side_effect_policy["kind"] == "read_only"

    w03 = directory.get("W03")
    assert w03.agent_id == GRAPH_RELATION_RETRIEVER
    assert w03.accepted_task_types == ["retrieve_financial_relations"]
    assert w03.output_types == ["GraphRelationResult"]
    assert "只查找关系" in w03.description

    w08 = directory.get("W08")
    assert w08.agent_id == DATABASE_WRITER
    assert w08.description == "负责写数据库。"
    assert set(w08.accepted_task_types) == {
        "write_portfolio_graph_context",
        "write_evidence_graph_context",
    }
    assert "commit_paper_trading_change" not in w08.accepted_task_types
    assert all(
        contract.side_effect_policy["kind"] == "derived_database_write"
        for contract in w08.task_contracts
    )

    w09 = directory.get("W09")
    assert w09.agent_id == ENTITY_ANALYST
    assert set(w09.accepted_task_types) == {
        "analyze_financial_entities",
        "compare_financial_entities",
    }
    assert w09.output_types == ["EntityAnalysisResult"]
    assert w09.side_effects == []


def test_private_tool_registry_preserves_worker_tool_boundary() -> None:
    class FakeProvider:
        pass

    registry = build_worker_tool_registry(provider=FakeProvider())
    collect = registry.get(EVIDENCE_COLLECT_EXTERNAL_TOOL)
    assert collect is not None
    assert collect.allowed_agent_types == [EVIDENCE_COLLECTOR]
    assert collect.side_effects == []
    assert collect.mutates_business_state is False

    portfolio_write = registry.get(DATABASE_WRITE_PORTFOLIO_GRAPH_CONTEXT)
    evidence_write = registry.get(DATABASE_WRITE_EVIDENCE_GRAPH_CONTEXT)
    assert portfolio_write is not None and evidence_write is not None
    assert portfolio_write.allowed_agent_types == [DATABASE_WRITER]
    assert evidence_write.allowed_agent_types == [DATABASE_WRITER]
    assert portfolio_write.side_effects == ["neo4j_write"]
    assert evidence_write.side_effects == ["neo4j_write"]


class _FakeRelationService:
    def find_relation_paths(self, *, source_refs, target_refs, as_of_time=""):
        return [
            GraphPathRef(
                path_id="relation_path:test",
                start_ref=source_refs[0],
                end_ref=target_refs[0],
                assertion_ids=["assertion:test"],
                object_ids=[target_refs[0].node_id],
                evidence_ids=[source_refs[0].node_id],
                path_type="financial_relation",
                confidence=0.8,
                explanation="relation exists",
            )
        ]

    def summarize_relations(self, paths):
        return {"target_count": 1, "path_count": len(paths), "targets": []}


def test_w03_returns_relations_without_business_interpretation() -> None:
    source = _ref("evidence:test", kind=GraphNodeKind.EVIDENCE, role="source")
    target = _ref("cn:security:sse:600519", role="target")
    task = GraphAgentTask(
        task_id="T03",
        run_id="run",
        session_id="session",
        worker_id="W03",
        assigned_agent=GRAPH_RELATION_RETRIEVER,
        objective="查找关系",
        task_type="retrieve_financial_relations",
        args={
            "relation_goal": "查找证据与目标之间的关系",
            "source_ref_ids": [source.node_id],
            "target_ref_ids": [target.node_id],
        },
        expected_output_type="GraphRelationResult",
        user_id="u",
        focus_refs=[source, target],
    )
    result = run_graph_impact(_FakeRelationService(), task, {}, {})
    assert result.status == ResultStatus.COMPLETED
    assert result.output_type == "GraphRelationResult"
    assert result.data["relation_paths"]
    assert result.metadata["business_interpretation"] is False
    assert "影响方向" not in result.summary


class _FakeLLM:
    def generate_json(self, **kwargs):
        validator = kwargs.get("validator")
        payload = {
            "entity_refs": [{"node_id": "cn:security:sse:600519"}],
            "facts": [{"text": "fact", "source_task_id": "T01"}],
            "analysis": [{"text": "analysis", "source_task_id": "T01"}],
            "model_signals": [],
            "relation_interpretations": [],
            "uncertainties": [{"text": "uncertain"}],
            "conclusion": "conclusion",
            "source_task_ids": ["T01"],
        }
        if validator:
            validator(payload)
        return payload


def test_w09_consumes_upstream_evidence_and_does_not_write() -> None:
    task = GraphAgentTask(
        task_id="T09",
        run_id="run",
        session_id="session",
        worker_id="W09",
        assigned_agent=ENTITY_ANALYST,
        objective="分析600519",
        task_type="analyze_financial_entities",
        args={"analysis_goal": "分析600519"},
        inputs={
            "evidence": [
                {"from_task_id": "T01", "expected_output_type": "EvidenceCollectionResult"}
            ]
        },
        expected_output_type="EntityAnalysisResult",
        user_id="u",
        focus_refs=[_ref("cn:security:sse:600519")],
    )
    resolved = {
        "evidence": [
            {
                "from_task_id": "T01",
                "output_type": "EvidenceCollectionResult",
                "status": "completed",
                "payload": {
                    "entity_refs": [{"node_id": "cn:security:sse:600519"}],
                    "collection_goal": "collect",
                    "results": [],
                    "record_count": 0,
                    "source_count": 0,
                    "write_performed": False,
                },
            }
        ]
    }
    result = run_entity_analysis(
        _FakeLLM(),
        task,
        {},
        resolved_inputs=resolved,
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert result.output_type == "EntityAnalysisResult"
    assert result.data["facts"]
    assert result.metadata["database_write"] is False
