from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.collaboration.models import (
    GraphAgentTask,
    GraphWorkerResult,
    MissingContextItem,
    ResultStatus,
)
from agent.collaboration.runtime_services import CollaborationRuntimeServices
from agent.runtime import AgentRuntimeRecorder, load_run_snapshot
from database.connection import initialize_database


def _task(run_id: str, *, task_id: str = "task_1", dependencies=None) -> GraphAgentTask:
    return GraphAgentTask(
        task_id=task_id,
        run_id=run_id,
        session_id="session-1",
        assigned_agent="PORTFOLIO_ANALYST",
        objective="load current portfolio snapshot",
        task_type="load_portfolio_snapshot",
        user_id="user-1",
        dependency_task_ids=list(dependencies or []),
        required_outputs=["portfolio_snapshot"],
        metadata={"request_mode": "analysis"},
    )


def _services(tmp_path):
    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)
    recorder = AgentRuntimeRecorder(
        user_id="user-1",
        goal="test worker runtime persistence",
        db_path=db_path,
        session_id="session-1",
    )
    services = CollaborationRuntimeServices.from_recorder(
        recorder,
        user_id="user-1",
        session_id="session-1",
    )
    return db_path, recorder, services


def test_worker_task_lifecycle_is_persisted_to_agent_steps(tmp_path) -> None:
    db_path, recorder, services = _services(tmp_path)
    task = _task(recorder.run_id)

    services.register_tasks([task])
    services.mark_ready(task)
    services.mark_running(task)
    services.record_result(
        task,
        GraphWorkerResult(
            task_id=task.task_id,
            agent_id=task.assigned_agent,
            status=ResultStatus.COMPLETED,
            summary="portfolio snapshot ready",
            confidence=0.9,
            metadata={"duration_ms": 5},
        ),
    )

    snapshot = load_run_snapshot(db_path, recorder.run_id)
    assert len(snapshot["steps"]) == 1
    step = snapshot["steps"][0]
    assert step["step_id"] == "task_1"
    assert step["intent"] == "load_portfolio_snapshot"
    assert step["status"] == "succeeded"
    assert step["depends_on_json"] == []
    assert step["observation_summary"] == "portfolio snapshot ready"
    assert step["metadata_json"]["runtime_layer"] == "worker_dag"
    assert step["metadata_json"]["agent_role"] == "PORTFOLIO_ANALYST"
    assert step["metadata_json"]["worker_result_status"] == "completed"
    assert [item["to"] for item in step["metadata_json"]["status_transitions"]] == [
        "ready",
        "running",
        "succeeded",
    ]


def test_dependency_task_and_need_context_are_persisted_without_failure(tmp_path) -> None:
    db_path, recorder, services = _services(tmp_path)
    upstream = _task(recorder.run_id, task_id="task_1")
    downstream = _task(
        recorder.run_id,
        task_id="task_2",
        dependencies=["task_1"],
    )

    services.register_tasks([upstream, downstream])
    services.mark_ready(downstream)
    services.mark_running(downstream)
    services.record_result(
        downstream,
        GraphWorkerResult(
            task_id=downstream.task_id,
            agent_id=downstream.assigned_agent,
            status=ResultStatus.NEED_CONTEXT,
            summary="account context required",
            missing_items=[
                MissingContextItem(
                    key="account_id",
                    description="account is required",
                )
            ],
        ),
    )

    snapshot = load_run_snapshot(db_path, recorder.run_id)
    by_id = {item["step_id"]: item for item in snapshot["steps"]}
    assert by_id["task_1"]["status"] == "ready"
    assert by_id["task_2"]["depends_on_json"] == ["task_1"]
    assert by_id["task_2"]["status"] == "skipped"
    assert by_id["task_2"]["metadata_json"]["worker_result_status"] == "need_context"
    assert by_id["task_2"]["metadata_json"]["missing_context_keys"] == ["account_id"]


def test_runtime_identity_mismatch_is_rejected(tmp_path) -> None:
    _, recorder, services = _services(tmp_path)

    with pytest.raises(ValueError, match="collaboration_runtime_identity_mismatch:run_id"):
        services.validate_identity(
            run_id=recorder.run_id + "-other",
            user_id="user-1",
            session_id="session-1",
        )


def test_unified_integration_reuses_the_formal_runtime_recorder(tmp_path, monkeypatch) -> None:
    from agent.collaboration import integration

    db_path = tmp_path / "agent_quant.db"
    initialize_database(db_path)
    recorder = AgentRuntimeRecorder(
        user_id="user-1",
        goal="integration recorder reuse",
        db_path=db_path,
        session_id="session-1",
    )
    captured = {}

    class FakeCoordinator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def execute(self, **kwargs):
            captured["execute"] = kwargs
            return {"graph_runtime": {}, "success": True, "execution_status": "completed"}

        def close(self):
            captured["closed"] = True

    binding = SimpleNamespace(
        service=object(),
        public_dict=lambda: {"profile_id": "test-profile"},
    )
    monkeypatch.setattr(integration, "AgentCollaborationCoordinator", FakeCoordinator)
    monkeypatch.setattr(integration, "require_run_llm_service", lambda **_: binding)

    result = integration.execute_unified_agent_request(
        query="test",
        user_id="user-1",
        db_path=db_path,
        session_id="session-1",
        run_id=recorder.run_id,
        llm_service=object(),
        runtime_recorder=recorder,
    )

    runtime_services = captured["runtime_services"]
    assert runtime_services.recorder is recorder
    assert runtime_services.run_id == recorder.run_id
    assert captured["execute"]["run_id"] == recorder.run_id
    assert captured["closed"] is True
    assert result["graph_runtime"]["llm_binding"]["single_service_identity"] is True


def test_current_coordinator_dag_persists_parallel_worker_results(tmp_path) -> None:
    from agent.collaboration.coordinator import AgentCollaborationCoordinator

    db_path, recorder, services = _services(tmp_path)
    first = _task(recorder.run_id, task_id="task_a")
    second = GraphAgentTask(
        task_id="task_b",
        run_id=recorder.run_id,
        session_id="session-1",
        assigned_agent="EVIDENCE_RETRIEVER",
        objective="load evidence",
        task_type="retrieve_evidence",
        user_id="user-1",
    )
    services.register_tasks([first, second])

    class FakeSpecialist:
        def run(self, task, **_kwargs):
            return GraphWorkerResult(
                task_id=task.task_id,
                agent_id=task.assigned_agent,
                status=ResultStatus.COMPLETED,
                summary=f"{task.task_id} completed",
                confidence=0.8,
            )

    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator.specialist = FakeSpecialist()
    coordinator.runtime_services = services

    results, batches, timeline = coordinator._run_dag(
        [first, second],
        query="test",
        output_dir=tmp_path,
        db_path=db_path,
        default_top_k=5,
        language="zh",
        execution_context={},
    )

    assert set(results) == {"task_a", "task_b"}
    assert batches[0]["parallel"] is True
    assert len(timeline) == 2

    snapshot = load_run_snapshot(db_path, recorder.run_id)
    by_id = {row["step_id"]: row for row in snapshot["steps"]}
    assert by_id["task_a"]["status"] == "succeeded"
    assert by_id["task_b"]["status"] == "succeeded"
    assert by_id["task_a"]["metadata_json"]["agent_role"] == "PORTFOLIO_ANALYST"
    assert by_id["task_b"]["metadata_json"]["agent_role"] == "EVIDENCE_RETRIEVER"
