from __future__ import annotations

from pathlib import Path

from agent.agent_specs import MARKET_INTELLIGENCE
from evaluation.multi_agent.exporter import export_benchmark
from evaluation.multi_agent.metrics import aggregate_metrics, handoff_counts, permission_violations, structured_output_errors
from evaluation.multi_agent.schemas import (
    BenchmarkRunResult,
    MULTI_AGENT_MODE,
    MultiAgentScenario,
    PermissionCheck,
)


def _scenario(**kwargs) -> MultiAgentScenario:
    return MultiAgentScenario(
        scenario_id=kwargs.get("scenario_id", "case_1"),
        name=kwargs.get("name", "case"),
        query=kwargs.get("query", "Show ranking and portfolio risk."),
        tasks=kwargs.get("tasks", [{"task_id": "task_1", "intent": "ranking", "parameters": {}, "depends_on": []}]),
        tags=kwargs.get("tags", []),
        expected_min_sources=kwargs.get("expected_min_sources", 1),
        permission_checks=kwargs.get("permission_checks", []),
    )


def _result(**kwargs) -> BenchmarkRunResult:
    return BenchmarkRunResult(
        scenario_id=kwargs.get("scenario_id", "case_1"),
        scenario_name=kwargs.get("scenario_name", "case"),
        mode=kwargs.get("mode", MULTI_AGENT_MODE),
        success=kwargs.get("success", True),
        execution_status=kwargs.get("execution_status", "completed"),
        latency_seconds=kwargs.get("latency_seconds", 0.1),
        task_count=kwargs.get("task_count", 2),
        successful_task_count=kwargs.get("successful_task_count", 2),
        tool_call_count=kwargs.get("tool_call_count", 2),
        permission_violation_count=kwargs.get("permission_violation_count", 0),
        permission_violations=kwargs.get("permission_violations", []),
        structured_output_valid=kwargs.get("structured_output_valid", True),
        structured_output_errors=kwargs.get("structured_output_errors", []),
        handoff_expected_count=kwargs.get("handoff_expected_count", 4),
        handoff_completed_count=kwargs.get("handoff_completed_count", 4),
        missing_handoff_count=kwargs.get("missing_handoff_count", 0),
        evidence_source_count=kwargs.get("evidence_source_count", 1),
        evidence_source_coverage=kwargs.get("evidence_source_coverage", 1.0),
        partial_failure_expected=kwargs.get("partial_failure_expected", False),
        partial_failure_recovered=kwargs.get("partial_failure_recovered", None),
        errors=kwargs.get("errors", []),
        warnings=kwargs.get("warnings", []),
    )


def test_phase2_metrics_calculate_required_values() -> None:
    metrics = aggregate_metrics(
        [
            _result(task_count=2, successful_task_count=2, latency_seconds=0.2, tool_call_count=3),
            _result(
                task_count=2,
                successful_task_count=1,
                latency_seconds=0.4,
                tool_call_count=1,
                permission_violation_count=1,
                structured_output_valid=False,
                handoff_completed_count=2,
                partial_failure_expected=True,
                partial_failure_recovered=True,
            ),
        ]
    )

    assert metrics["task_success_rate"] == 0.75
    assert metrics["role_handoff_completion_rate"] == 0.75
    assert metrics["tool_permission_violation_count"] == 1
    assert metrics["structured_output_valid_rate"] == 0.5
    assert metrics["partial_failure_recovery_rate"] == 1.0
    assert metrics["average_tool_call_count"] == 2


def test_phase2_export_generates_json_csv_markdown_even_with_failure(tmp_path: Path) -> None:
    results = [
        _result(),
        _result(
            scenario_id="failed_case",
            scenario_name="failed case",
            success=False,
            structured_output_valid=False,
            structured_output_errors=["missing_agent_outputs:reporting"],
            missing_handoff_count=1,
        ),
    ]
    payload = {
        "metrics": aggregate_metrics(results),
        "metrics_by_mode": {MULTI_AGENT_MODE: aggregate_metrics(results)},
        "results": [item.to_dict() for item in results],
    }

    artifacts = export_benchmark(output_root=tmp_path, payload=payload, results=results)

    assert Path(artifacts["details_json"]).exists()
    assert Path(artifacts["summary_csv"]).exists()
    report = Path(artifacts["report_markdown"]).read_text(encoding="utf-8")
    assert "failed_case" in report
    assert "Metric Definitions" in report


def test_phase2_permission_violation_count_uses_agent_whitelist() -> None:
    scenario = _scenario(
        permission_checks=[
            PermissionCheck(MARKET_INTELLIGENCE, "paper_trade_execute", "must be blocked")
        ]
    )

    violations = permission_violations(scenario, mode=MULTI_AGENT_MODE, tool_calls=[])

    assert len(violations) == 1
    assert violations[0]["tool_name"] == "paper_trade_execute"


def test_phase2_handoff_missing_is_detected() -> None:
    scenario = _scenario()
    timeline = [
        {"role": "supervisor", "message_id": "m1", "handoff_from": "user", "handoff_to": "market_intelligence"},
        {"role": "market_intelligence", "message_id": "m2", "handoff_from": "supervisor", "handoff_to": ""},
    ]

    expected, completed, missing = handoff_counts(scenario, mode=MULTI_AGENT_MODE, role_timeline=timeline)

    assert expected == 4
    assert completed == 1
    assert missing == 3


def test_phase2_structured_output_validation_requires_agent_protocol_fields() -> None:
    scenario = _scenario()

    errors = structured_output_errors(
        scenario,
        mode=MULTI_AGENT_MODE,
        raw_result={"execution_status": "completed"},
        task_results={},
        tool_calls=[],
        agent_outputs={"supervisor": {"role": "supervisor", "status": "succeeded"}},
    )

    assert any(item.startswith("missing_agent_outputs:") for item in errors)
    assert "missing_message_id:supervisor" in errors
