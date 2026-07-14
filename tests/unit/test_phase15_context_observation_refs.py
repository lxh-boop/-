from pathlib import Path

from agent.context.context_builder import ContextManager
from agent.react import (
    ObservationEvent,
    ObservationSeverity,
    ObservationType,
    ReplanPolicy,
    attach_observation_refs_to_context_bundle,
)


def test_phase15_context_refs_include_observation_refs_not_payload(tmp_path: Path):
    bundle = ContextManager(output_dir=tmp_path).create_initial_context(
        user_id="u1",
        query="q",
        conversation_id="conv_1",
        run_id="run_1",
    )
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TASK_FAILED,
        severity=ObservationSeverity.BLOCKING,
        summary="blocked",
        detail={"raw_tool_payload": {"secret": "hidden"}},
    )
    decision = ReplanPolicy().build_replan_decision(event)

    attach_observation_refs_to_context_bundle(bundle, event, decision)
    minimal = bundle.to_minimal_context()

    assert minimal["observation_refs"][0]["observation_id"] == event.observation_id
    assert minimal["blocking_observation_ids"] == [event.observation_id]
    assert minimal["latest_replan_decision_id"] == decision.replan_decision_id
    assert "raw_tool_payload" not in str(minimal)
    assert "hidden" not in str(minimal)


def test_phase15_context_keeps_existing_memory_refs_safe(tmp_path: Path):
    bundle = ContextManager(output_dir=tmp_path).create_initial_context(
        user_id="u1",
        query="q",
        conversation_id="conv_1",
        run_id="run_1",
    )
    minimal = bundle.to_minimal_context()

    assert "memory_records" not in str(minimal)
    assert "confirmation_token" not in str(minimal)
    assert isinstance(bundle.memory_context.memory_refs, list)
