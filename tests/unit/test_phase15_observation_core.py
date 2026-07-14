from agent.react import (
    ObservationEvent,
    ObservationSeverity,
    ObservationStatus,
    ObservationType,
    ObservationWindow,
)


def test_phase15_observation_event_serializes_roundtrip():
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        source_tool_name="portfolio.get_state",
        observation_type=ObservationType.TOOL_SUCCESS,
        status=ObservationStatus.RECORDED,
        severity=ObservationSeverity.INFO,
        summary="tool completed",
        artifact_refs=[{"artifact_id": "art_1"}],
        memory_refs=[{"memory_id": "mem_1"}],
    )

    data = event.to_dict()
    assert data["observation_id"].startswith("obs_")
    assert data["observation_type"] == "TOOL_SUCCESS"
    assert data["artifact_refs"] == [{"artifact_id": "art_1"}]

    restored = ObservationEvent.from_dict(data)
    assert restored.observation_type is ObservationType.TOOL_SUCCESS
    assert restored.status is ObservationStatus.RECORDED
    assert restored.severity is ObservationSeverity.INFO


def test_phase15_observation_type_contract_complete():
    required = {
        "TOOL_SUCCESS",
        "TOOL_EMPTY_RESULT",
        "TOOL_ERROR",
        "TOOL_PERMISSION_BLOCKED",
        "CONTEXT_INSUFFICIENT",
        "EVIDENCE_INSUFFICIENT",
        "MEMORY_HIT",
        "MEMORY_EMPTY",
        "APPROVAL_REQUIRED",
        "APPROVAL_DENIED",
        "TASK_PARTIAL_SUCCESS",
        "TASK_FAILED",
        "REPORT_READY",
        "USER_CLARIFICATION_NEEDED",
        "SYSTEM_WARNING",
    }
    assert required <= {item.value for item in ObservationType}


def test_phase15_observation_window_keeps_blocking_observation():
    observations = [
        ObservationEvent(
            observation_type=ObservationType.TOOL_SUCCESS,
            severity=ObservationSeverity.INFO,
            summary="ok " + ("x" * 500),
        ),
        ObservationEvent(
            observation_type=ObservationType.TASK_FAILED,
            severity=ObservationSeverity.BLOCKING,
            summary="must keep",
        ),
    ]

    window = ObservationWindow(default_budget=180)
    trimmed = window.trim_observations_to_budget(observations, budget=180)
    assert any(item.get("summary") == "must keep" for item in trimmed)


def test_phase15_observation_window_summarizes_old_observations():
    event = ObservationEvent(
        observation_type=ObservationType.APPROVAL_REQUIRED,
        severity=ObservationSeverity.MEDIUM,
        summary="approval needed",
        approval_refs=[{"plan_id": "plan_1", "token_present": True}],
    )
    summaries = ObservationWindow().summarize_old_observations([event])
    assert summaries[0].replan_required is True
    assert summaries[0].approval_refs == [{"plan_id": "plan_1", "token_present": True}]
