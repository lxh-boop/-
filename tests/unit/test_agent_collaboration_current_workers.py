"""Current Worker runtime behavior after private-tool planning refactor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock

from agent.collaboration.agent_directory import (
    EVIDENCE_RETRIEVER,
    REPORT_WRITER,
    RISK_ANALYST,
    SYSTEM_DIAGNOSTIC,
)
from agent.collaboration.models import (
    GraphAgentTask,
    ResultStatus,
    TaskStatus,
)
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.worker_tools import (
    DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL,
    RISK_ANALYZE_TOOL,
    build_worker_tool_directory,
    build_worker_tool_registry,
)


class FakeLLM:
    settings = SimpleNamespace()
    profile_id = "test"
    config_hash = "test"

    def __init__(
        self,
        *,
        plan: dict | None = None,
        text: str = "汇总结果",
    ) -> None:
        self.plan = plan or {}
        self.text = text
        self.text_calls: list[dict] = []

    def generate_json(self, *, validator=None, **_: object):
        payload = json.loads(json.dumps(self.plan))
        if validator:
            validator(payload)
        return payload

    def generate_text(self, **kwargs: object) -> str:
        self.text_calls.append(dict(kwargs))
        return self.text


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
    capability_id: str,
    *,
    focus_refs: list[GraphRef] | None = None,
) -> GraphAgentTask:
    return GraphAgentTask(
        task_id=f"task-{capability_id}",
        run_id="run-1",
        session_id="session-1",
        assigned_agent=assigned_agent,
        objective="test objective",
        task_type=task_type,
        user_id="user-1",
        capability_id=capability_id,
        focus_refs=focus_refs or [],
    )


def _runtime(
    provider: object,
    *,
    llm_service: object,
    impact_service: object | None = None,
) -> SpecialistRuntime:
    backend = provider
    registry = build_worker_tool_registry(
        evidence_backend=backend,
        portfolio_backend=backend,
        risk_backend=backend,
        diagnostic_backend=backend,
        impact_backend=impact_service or SimpleNamespace(),
    )
    return SpecialistRuntime(
        llm_service=llm_service,
        worker_tool_directory=build_worker_tool_directory(registry),
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


def test_evidence_worker_uses_provided_evidence_without_tool_plan() -> None:
    provider = SimpleNamespace()
    task = _task(
        EVIDENCE_RETRIEVER,
        "retrieve_evidence",
        "evidence.retrieve",
        focus_refs=[
            _ref("evidence:1", GraphNodeKind.EVIDENCE, "cause")
        ],
    )

    result = _run(
        _runtime(provider, llm_service=FakeLLM()),
        task,
    )

    assert result.status == ResultStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert result.metadata["capability_id"] == "evidence.retrieve"
    assert result.metadata["tool_plan"]["tool_call_count"] == 0


def test_risk_worker_returns_structured_context_request() -> None:
    llm = FakeLLM(
        plan={
            "steps": [
                {
                    "step_id": "risk",
                    "tool_name": RISK_ANALYZE_TOOL,
                    "objective": "analyze risk",
                    "dependency_step_ids": [],
                    "required_outputs": ["risk_analysis"],
                    "proposed_arguments": {},
                }
            ]
        }
    )
    task = _task(
        RISK_ANALYST,
        "analyze_risk",
        "risk.analyze",
    )

    result = _run(
        _runtime(
            SimpleNamespace(analyze_risk=Mock()),
            llm_service=llm,
        ),
        task,
    )

    assert result.status == ResultStatus.NEED_CONTEXT
    assert task.status == TaskStatus.WAITING_CONTEXT
    assert result.context_request is not None
    assert result.context_request.source_capability_id == "risk.analyze"
    assert [
        item.key for item in result.context_request.requirements
    ] == ["active_graph_refs"]


def test_report_writer_is_a_reasoning_only_terminal_worker() -> None:
    llm = FakeLLM(text="汇总结果")
    task = _task(
        REPORT_WRITER,
        "write_report",
        "report.write",
    )
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
        _runtime(SimpleNamespace(), llm_service=llm),
        task,
        dependencies,
    )

    assert result.status == ResultStatus.COMPLETED
    assert result.summary == "汇总结果"
    assert len(llm.text_calls) == 1


def test_system_diagnostic_runs_through_private_tool() -> None:
    store = SimpleNamespace(
        verify_connectivity=Mock(),
        graph_id="financial_graph",
    )
    llm = FakeLLM(
        plan={
            "steps": [
                {
                    "step_id": "connectivity",
                    "tool_name": DIAGNOSTIC_GRAPH_CONNECTIVITY_TOOL,
                    "objective": "check graph",
                    "dependency_step_ids": [],
                    "required_outputs": ["diagnostic_analysis"],
                    "proposed_arguments": {},
                }
            ]
        }
    )
    provider = SimpleNamespace(
        check_connectivity=Mock(
            side_effect=lambda: (
                store.verify_connectivity(),
                {
                    "success": True,
                    "status": "ok",
                    "graph_id": store.graph_id,
                },
            )[1]
        )
    )
    task = _task(
        SYSTEM_DIAGNOSTIC,
        "diagnose_system",
        "system.check_graph_connectivity",
    )

    result = _run(_runtime(provider, llm_service=llm), task)

    assert result.status == ResultStatus.COMPLETED
    assert store.verify_connectivity.call_count == 1
    assert result.metadata["tool_plan"]["tool_call_count"] == 1


def test_unknown_capability_is_not_executed() -> None:
    task = _task(
        "UNKNOWN_WORKER",
        "unknown",
        "unknown.capability",
    )

    result = _run(
        _runtime(SimpleNamespace(), llm_service=FakeLLM()),
        task,
    )

    assert result.status == ResultStatus.NOT_EXECUTED
    assert "unknown_worker_capability" in result.warnings[0]
