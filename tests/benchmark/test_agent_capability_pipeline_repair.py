from __future__ import annotations

import json

from agent.llm_audit import activate_llm_audit_context, load_llm_events, record_llm_call, record_schema_result
from benchmarks.agent_capability.run_benchmark import _rows_for_cases
from benchmarks.agent_capability.scoring import assess_trace_validity, aggregate_metrics, metric_records


def _event(tmp_path, *, stage: str, success: bool = True, schema: bool = True) -> dict:
    activate_llm_audit_context(
        run_id="agent_run_test",
        conversation_id="conversation_test",
        output_dir=tmp_path,
        case_id="L1-A-025",
        iteration=1,
        formal_entry_used=True,
        formal_entry_name="agent.executor.run_agent_request",
    )
    event_id = record_llm_call(
        stage=stage,
        provider="openai_compatible",
        model="test-model",
        temperature=0.0,
        request_at="2026-01-01T00:00:00+00:00",
        response_at="2026-01-01T00:00:01+00:00",
        duration_ms=1000,
        success=success,
        error_type="RateLimitError" if not success else "",
        error_message="api_key=super-secret" if not success else "",
    )
    if success:
        record_schema_result(event_id, schema)
    return load_llm_events(tmp_path, "agent_run_test")[-1]


def _trace(events: list[dict], *, formal: bool = True, legal_terminal_before_reviewer: bool = False) -> dict:
    return {
        "llm_events": events,
        "trace_persisted": bool(events),
        "legal_terminal_before_reviewer": legal_terminal_before_reviewer,
        "formal_entry": {
            "formal_entry_used": formal,
            "formal_entry_name": "agent.executor.run_agent_request" if formal else "",
        },
    }


def test_real_llm_planner_and_reviewer_events_are_persisted_and_redacted(tmp_path):
    planner = _event(tmp_path, stage="planner")
    reviewer = _event(tmp_path, stage="goal_reviewer")
    events = load_llm_events(tmp_path, "agent_run_test")

    assert {event["stage"] for event in events} == {"planner", "goal_reviewer"}
    assert all(event["event_type"] == "LLM_CALL" for event in events)
    assert all(event["formal_entry_name"] == "agent.executor.run_agent_request" for event in events)
    assert "super-secret" not in json.dumps(events, ensure_ascii=False)
    assert planner["response_schema_valid"] is True
    assert planner["covered_stages"] == ["planner"]
    assert reviewer["fallback_used"] is False and reviewer["mock_used"] is False


def test_validity_allows_terminal_before_reviewer_but_excludes_provider_and_trace_failures(tmp_path):
    planner = _event(tmp_path, stage="planner")
    terminal = assess_trace_validity(_trace([planner], legal_terminal_before_reviewer=True))
    assert terminal["valid_for_agent_scoring"]
    assert not terminal["reviewer_required"]

    reviewer = _event(tmp_path, stage="goal_reviewer")
    valid = assess_trace_validity(_trace([planner, reviewer]))
    assert valid["valid_for_agent_scoring"]
    assert valid["reviewer_required"]

    failed_planner = _event(tmp_path, stage="planner", success=False)
    provider = assess_trace_validity(_trace([failed_planner]))
    assert provider["provider_failure"] and not provider["valid_for_agent_scoring"]

    missing = assess_trace_validity(_trace([], formal=True))
    assert missing["infrastructure_failure"] and not missing["valid_for_agent_scoring"]


def test_formal_entry_cannot_be_forged_by_runner_data(tmp_path):
    planner = _event(tmp_path, stage="planner")
    reviewer = _event(tmp_path, stage="goal_reviewer")
    result = assess_trace_validity(_trace([planner, reviewer], formal=False))
    assert not result["valid_for_agent_scoring"]
    assert "formal_entry_missing" in result["failure_reasons"]


def test_zero_valid_agent_metrics_are_all_na_with_denominators():
    metrics = aggregate_metrics([])
    records = metric_records(metrics, scored_sample_count=0)
    assert metrics["forbidden_capability_rate"] is None
    assert metrics["unauthorized_write_rate"] is None
    assert all(record["status"] == "N/A" for record in records.values())
    assert all(record["denominator"] == 0 for record in records.values())


def test_resume_retries_invalid_infrastructure_runs():
    cases = [{"case_id": "L1-A-025"}]
    invalid = [{"run_key": "L1-A-025:1:cfg", "validity": {"valid_for_agent_scoring": False}}]
    valid = [{"run_key": "L1-A-025:1:cfg", "validity": {"valid_for_agent_scoring": True}}]
    assert _rows_for_cases(invalid, cases, 1, "cfg") == [(cases[0], 1)]
    assert _rows_for_cases(valid, cases, 1, "cfg") == []
