import json
from pathlib import Path

from agent.react import (
    ObservationEvent,
    ObservationSeverity,
    ObservationStatus,
    ObservationType,
    ObserveStore,
    ReActStep,
    ReActTrace,
)


def test_phase15_observe_store_save_load_and_query(tmp_path: Path):
    store = ObserveStore(output_dir=tmp_path)
    event = ObservationEvent(
        conversation_id="conv_1",
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TOOL_EMPTY_RESULT,
        severity=ObservationSeverity.MEDIUM,
        summary="empty",
    )

    saved = store.save_observation(event, user_id="u1")

    loaded = store.load_observation(saved.observation_id, user_id="u1")
    assert loaded is not None
    assert loaded.status is ObservationStatus.RECORDED
    assert store.list_observations_by_run("run_1", user_id="u1")[0].observation_id == saved.observation_id
    assert store.list_observations_by_conversation("conv_1", user_id="u1")[0].task_id == "task_1"
    assert store.list_observations_by_task("task_1", user_id="u1", run_id="run_1")[0].summary == "empty"


def test_phase15_observe_store_secret_does_not_land_on_disk(tmp_path: Path):
    store = ObserveStore(output_dir=tmp_path)
    event = ObservationEvent(
        run_id="run_secret",
        task_id="task_secret",
        observation_type=ObservationType.TOOL_ERROR,
        summary="failed confirmation_token=abc123 api_key=sk-test",
        detail={
            "confirmation_token": "abc123",
            "api_key": "sk-test",
            "db_path": r"D:\stock_daily_app\data\agent_quant.db",
        },
    )

    store.save_observation(event, user_id="u1")

    path = tmp_path / "react_logs" / "u1" / "run_secret.jsonl"
    text = path.read_text(encoding="utf-8")
    assert "abc123" not in text
    assert "sk-test" not in text
    assert "agent_quant.db" not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert rows[0]["kind"] == "observation"


def test_phase15_observe_store_blocking_and_expire(tmp_path: Path):
    store = ObserveStore(output_dir=tmp_path)
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TASK_FAILED,
        severity=ObservationSeverity.BLOCKING,
        summary="blocked",
    )
    saved = store.save_observation(event, user_id="u1")

    assert store.list_blocking_observations(user_id="u1", run_id="run_1")[0].observation_id == saved.observation_id
    assert store.expire_observations(user_id="u1", run_id="run_1", observation_ids=[saved.observation_id]) == 1
    expired = store.load_observation(saved.observation_id, user_id="u1")
    assert expired is not None
    assert expired.status is ObservationStatus.EXPIRED


def test_phase15_react_trace_appends_steps_and_edges():
    trace = ReActTrace(run_id="run_1")
    step = trace.add_step(
        ReActStep(
            task_id="task_1",
            thought_summary="need readonly evidence",
            action_summary="call rag",
            tool_name="stock.rag",
        )
    )
    trace.add_observation_edge(step_id=step.step_id, observation_id="obs_1")
    trace.add_tool_call_edge(step_id=step.step_id, tool_call_id="call_1", tool_name="stock.rag")
    trace.add_artifact_edge(step_id=step.step_id, artifact_id="art_1")
    trace.add_approval_edge(step_id=step.step_id, plan_id="plan_1", status="pending")
    trace.add_memory_edge(step_id=step.step_id, memory_id="mem_1")

    data = trace.to_dict()
    assert data["observation_ids"] == ["obs_1"]
    assert data["steps"][0]["observation_id"] == "obs_1"
    assert data["tool_call_edges"][0]["tool_call_id"] == "call_1"
    assert ReActTrace.from_dict(data).steps[0].thought_summary == "need readonly evidence"
