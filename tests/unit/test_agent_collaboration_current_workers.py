"""Regression tests for the current domain-scoped Worker runtime.

The suite verifies dispatch and result-contract behavior without external LLM,
Neo4j, portfolio, or evidence-service calls.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import (
    EVIDENCE_RETRIEVER,
    GRAPH_IMPACT_ANALYST,
    PORTFOLIO_ANALYST,
    REPORT_WRITER,
    RISK_ANALYST,
    STRATEGY_GUARD,
    SYSTEM_DIAGNOSTIC,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus, TaskStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef


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


def test_evidence_worker_uses_provided_evidence_without_provider_call() -> None:
    provider = SimpleNamespace(analyze_entities=Mock(), retrieve_evidence=Mock())
    task = _task(
        EVIDENCE_RETRIEVER,
        "retrieve_evidence",
        focus_refs=[_ref("evidence:1", GraphNodeKind.EVIDENCE, "cause")],
    )

    result = _run(_runtime(provider), task)

    assert result.status == ResultStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert result.metadata["task_type"] == "retrieve_evidence"
    provider.analyze_entities.assert_not_called()
    provider.retrieve_evidence.assert_not_called()


def test_portfolio_worker_preserves_snapshot_result_contract() -> None:
    portfolio_ref = _ref("portfolio:user-1", GraphNodeKind.OBJECT, "portfolio")
    holding_ref = _ref("object:600519", GraphNodeKind.OBJECT, "holding")
    provider = SimpleNamespace(
        load_portfolio_snapshot=Mock(
            return_value={
                "success": True,
                "portfolio_ref": portfolio_ref.to_dict(),
                "holding_refs": [holding_ref.to_dict()],
                "unresolved_positions": [],
                "portfolio": {"position_count": 1},
            }
        )
    )
    task = _task(PORTFOLIO_ANALYST, "load_portfolio_snapshot")

    result = _run(_runtime(provider), task)

    assert result.status == ResultStatus.COMPLETED
    assert result.findings[0]["holding_count"] == 1
    assert result.metadata["produced_refs"][0]["node_id"] == "portfolio:user-1"
    provider.load_portfolio_snapshot.assert_called_once()


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


def test_graph_impact_worker_reports_missing_portfolio_before_query() -> None:
    impact_service = SimpleNamespace(find_paths=Mock(), summarize_paths=Mock())
    runtime = SpecialistRuntime(
        llm_service=SimpleNamespace(),
        provider=SimpleNamespace(),
        impact_service=impact_service,
    )
    task = _task(
        GRAPH_IMPACT_ANALYST,
        "map_evidence_to_holdings",
        focus_refs=[_ref("evidence:1", GraphNodeKind.EVIDENCE, "cause")],
    )

    result = _run(runtime, task)

    assert result.status == ResultStatus.NEED_CONTEXT
    assert [item.key for item in result.missing_items] == ["portfolio_snapshot_ref"]
    impact_service.find_paths.assert_not_called()


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
