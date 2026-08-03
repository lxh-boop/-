"""Regression tests for the current domain-scoped Worker runtime.

The suite verifies dispatch and result-contract behavior without external LLM,
Neo4j, portfolio, or evidence-service calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import (
    EVIDENCE_RETRIEVER,
    ENTITY_ANALYST,
    GRAPH_CONTEXT_MANAGER,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
    W08,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus, TaskStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.services.evidence_service import EvidenceService
from agent.worker_tools import (
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    EVIDENCE_SEARCH_NEWS_TOOL,
)


def _ref(node_id: str, node_kind: GraphNodeKind, role: str) -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id=node_id,
        node_kind=node_kind,
        role=role,
    )


def _task(
    assigned_agent: str,
    task_type: str,
    *,
    focus_refs: list[GraphRef] | None = None,
) -> GraphAgentTask:
    return GraphAgentTask(
        task_id=f"task-{assigned_agent.lower()}",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=assigned_agent,
        objective="test objective",
        task_type=task_type,
        user_id="user-1",
        focus_refs=focus_refs or [],
    )


def _runtime(provider: object, *, llm_service: object | None = None) -> SpecialistRuntime:
    return SpecialistRuntime(
        llm_service=llm_service or SimpleNamespace(),
        provider=provider,
        impact_service=SimpleNamespace(),
    )


def _run(runtime: SpecialistRuntime, task: GraphAgentTask, dependencies=None):
    return runtime.run(
        task,
        current_user_request="test request",
        dependency_results=dependencies or {},
        output_dir="outputs",
        db_path=None,
        default_top_k=5,
        language="zh",
    )


class _EvidenceToolDagLLM:
    def generate_json(self, **kwargs):
        payload = {
            "goal_contract": {
                "goal_summary": "收集外部证据",
                "required_output_keys": [
                    "validated_evidence_collection",
                    "results",
                    "record_count",
                    "source_count",
                    "coverage",
                ],
                "completion_criteria": ["返回校验后的证据集合"],
            },
            "tasks": [
                {
                    "tool_task_id": "TT1",
                    "tool_name": EVIDENCE_SEARCH_NEWS_TOOL,
                    "objective": "读取新闻和公告",
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
                    "tool_name": EVIDENCE_FINALIZE_COLLECTION_TOOL,
                    "objective": "合并并校验证据",
                    "args": {},
                    "inputs": {
                        "collections": [{"from_tool_task_id": "TT1"}],
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
            "final_output_task_ids": ["TT2"],
        }
        validator = kwargs.get("validator")
        if validator:
            validator(payload)
        return payload


def test_evidence_worker_collects_entity_set_without_database_write(monkeypatch) -> None:
    entity_ref = _ref("cn:security:sse:600519", GraphNodeKind.OBJECT, "focus")
    monkeypatch.setattr(
        EvidenceService,
        "search_news",
        lambda self, code, **kwargs: {
            "success": True,
            "data": {
                "records": [{"title": "evidence", "text": "body"}],
                "sources": [{"source": "test"}],
            },
        },
    )
    provider = SimpleNamespace(
        provider_symbol=Mock(return_value="600519"),
    )
    task = GraphAgentTask(
        task_id="task-evidence",
        run_id="run-1",
        session_id="session-1",
        worker_id="W01",
        assigned_agent=EVIDENCE_RETRIEVER,
        objective="收集外部证据",
        task_type="collect_external_evidence",
        user_id="user-1",
        args={
            "entity_ref_ids": [entity_ref.node_id],
            "collection_goal": "收集600519外部证据",
        },
        focus_refs=[entity_ref],
        expected_output_type="EvidenceCollectionResult",
    )

    result = _run(_runtime(provider, llm_service=_EvidenceToolDagLLM()), task)

    assert result.status == ResultStatus.COMPLETED
    assert result.output_type == "EvidenceCollectionResult"
    assert result.payload["write_performed"] is False
    assert result.metadata["database_write"] is False
    assert result.metadata["tool_dag_used"] is True
    provider.provider_symbol.assert_called_once()

def test_w02_portfolio_query_is_read_only_and_does_not_materialize_graph() -> None:
    holding_ref = _ref("cn:security:sse:600519", GraphNodeKind.OBJECT, "holding")
    identity = SimpleNamespace(
        resolve_request=Mock(
            return_value=SimpleNamespace(
                ambiguous_mentions=[],
                refs=[holding_ref],
            )
        )
    )
    provider = SimpleNamespace(
        identity=identity,
        public_entity_descriptor=Mock(
            return_value={
                "entity_ref": holding_ref.to_dict(),
                "public_code": "600519",
                "display_label": "贵州茅台",
                "exchange": "SSE",
                "identity_source": "graph_identity",
                "identity_locked": True,
            }
        ),
        read_portfolio_state=Mock(
            return_value={
                "success": True,
                "message": "ok",
                "portfolio": {
                    "account": {"total_assets": 100000.0},
                    "active_positions": [
                        {
                            "stock_code": "600519",
                            "stock_name": "贵州茅台",
                            "quantity": 10,
                            "market_value": 15000.0,
                        }
                    ],
                    "cash": 85000.0,
                    "total_assets": 100000.0,
                    "cash_state": {
                        "cash_ratio": 0.85,
                        "position_market_value": 15000.0,
                    },
                    "as_of_date": "2026-08-02",
                    "snapshot_id": "business-snapshot-1",
                },
            }
        ),
        materialize_portfolio_snapshot=Mock(),
    )
    task = _task(PORTFOLIO_ANALYST, "query_portfolio_state")

    result = _run(_runtime(provider), task)

    assert result.status == ResultStatus.COMPLETED
    assert result.payload["graph_snapshot_materialized"] is False
    assert result.payload["display_positions"][0]["public_code"] == "600519"
    provider.read_portfolio_state.assert_called_once()
    provider.materialize_portfolio_snapshot.assert_not_called()


def test_w08_writes_upstream_portfolio_graph_context_to_database() -> None:
    portfolio_ref = _ref("portfolio_snapshot:user-1:abc", GraphNodeKind.OBJECT, "portfolio")
    holding_ref = _ref("cn:security:sse:600519", GraphNodeKind.OBJECT, "holding")
    provider = SimpleNamespace(
        materialize_portfolio_snapshot=Mock(
            return_value={
                "success": True,
                "portfolio_ref": portfolio_ref.to_dict(),
                "holding_refs": [holding_ref.to_dict()],
                "unresolved_positions": [],
                "graph_write": {"patch_id": "patch-1"},
            }
        )
    )
    task = GraphAgentTask(
        task_id="task-w08",
        run_id="run-1",
        session_id="session-1",
        worker_id=W08,
        assigned_agent=GRAPH_CONTEXT_MANAGER,
        objective="写入组合图上下文",
        task_type="write_portfolio_graph_context",
        user_id="user-1",
        args={"user_id": "user-1", "as_of_time": "2026-08-02"},
        inputs={
            "portfolio_state": [
                {
                    "from_task_id": "task-w02",
                    "expected_output_type": "PortfolioAnalysisResult",
                }
            ]
        },
        expected_output_type="PortfolioGraphContextResult",
        dependency_task_ids=["task-w02"],
        metadata={"structured_worker_contract": True},
    )
    dependencies = {
        "task-w02": {
            "output_type": "PortfolioAnalysisResult",
            "payload_schema": "portfolio_analysis_result.v1",
            "payload": {
                "entity_catalog": [],
                "display_positions": [],
                "account_snapshot": {"total_assets": 100000.0},
                "portfolio_totals": {
                    "cash": 85000.0,
                    "total_assets": 100000.0,
                    "position_market_value": 15000.0,
                },
                "portfolio_summary": {},
                "unresolved_positions": [],
                "as_of_time": "2026-08-02",
                "graph_snapshot_materialized": False,
            },
            "status": "completed",
            "summary": "portfolio read",
        }
    }

    result = _run(_runtime(provider), task, dependencies)

    assert result.status == ResultStatus.COMPLETED
    assert result.output_type == "PortfolioGraphContextResult"
    assert result.payload["portfolio_ref"]["node_id"] == portfolio_ref.node_id
    assert result.metadata["database_write"] is True
    provider.materialize_portfolio_snapshot.assert_called_once()

def test_risk_worker_keeps_dependency_ref_and_provider_call() -> None:
    portfolio_ref = _ref("portfolio:user-1", GraphNodeKind.OBJECT, "portfolio")
    provider = SimpleNamespace(
        analyze_risk=Mock(
            return_value={
                "success": True,
                "message": "ok",
                "data": {"risk_level": "medium"},
                "records": [],
                "warnings": [],
            }
        )
    )
    task = _task(RISK_ANALYST, "analyze_risk")
    dependencies = {
        "portfolio": {
            "focus_refs": [portfolio_ref.to_dict()],
            "metadata": {"produced_refs": [portfolio_ref.to_dict()]},
        }
    }

    result = _run(_runtime(provider), task, dependencies)

    assert result.status == ResultStatus.COMPLETED
    assert result.focus_refs == [portfolio_ref]
    provider.analyze_risk.assert_called_once()
    assert provider.analyze_risk.call_args.kwargs["portfolio_ref"] == portfolio_ref


def test_graph_relation_worker_reports_missing_target_before_query() -> None:
    impact_service = SimpleNamespace(find_relation_paths=Mock(), summarize_relations=Mock())
    runtime = SpecialistRuntime(
        llm_service=SimpleNamespace(),
        provider=SimpleNamespace(),
        impact_service=impact_service,
    )
    task = _task(
        GRAPH_IMPACT_ANALYST,
        "retrieve_financial_relations",
        focus_refs=[_ref("evidence:1", GraphNodeKind.EVIDENCE, "source")],
    )

    result = _run(runtime, task)

    assert result.status == ResultStatus.NEED_CONTEXT
    assert [item.key for item in result.missing_items] == ["target_graph_context"]
    impact_service.find_relation_paths.assert_not_called()

def test_report_writer_uses_only_dependency_results() -> None:
    llm_service = SimpleNamespace(generate_text=Mock(return_value="汇总结果"))
    task = _task(REPORT_WRITER, "write_report")
    dependencies = {
        "evidence": {
            "contract_version": "graph_worker_result.v1",
            "task_id": "evidence",
            "agent_id": EVIDENCE_RETRIEVER,
            "status": "completed",
            "summary": "evidence ready",
            "confidence": 0.8,
        }
    }

    result = _run(
        _runtime(SimpleNamespace(), llm_service=llm_service),
        task,
        dependencies,
    )

    assert result.status == ResultStatus.COMPLETED
    assert result.summary == "汇总结果"
    llm_service.generate_text.assert_called_once()


def test_strategy_guard_keeps_empty_proposal_catalog_safe(monkeypatch) -> None:
    from agent import tool_engine

    registry = SimpleNamespace(list=Mock(return_value=[]))
    monkeypatch.setattr(tool_engine, "get_tool_registry_v2", lambda: registry)
    task = _task(STRATEGY_GUARD, "build_proposal")

    result = _run(_runtime(SimpleNamespace()), task)

    assert result.status == ResultStatus.FAILED
    assert result.warnings == ["proposal_capability_catalog_empty"]


def test_system_diagnostic_uses_graph_connectivity_only() -> None:
    store = SimpleNamespace(verify_connectivity=Mock(), graph_id="financial_graph")
    provider = SimpleNamespace(identity=SimpleNamespace(store=store))
    task = _task(SYSTEM_DIAGNOSTIC, "diagnose_system")

    result = _run(_runtime(provider), task)

    assert result.status == ResultStatus.COMPLETED
    assert result.findings[0]["graph_id"] == "financial_graph"
    store.verify_connectivity.assert_called_once()


def test_unknown_worker_is_not_executed() -> None:
    task = _task("UNKNOWN_WORKER", "unknown")

    result = _run(_runtime(SimpleNamespace()), task)

    assert result.status == ResultStatus.NOT_EXECUTED
    assert task.status == TaskStatus.FAILED
