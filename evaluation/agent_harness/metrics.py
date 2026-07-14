from __future__ import annotations

from statistics import mean
from typing import Any

from evaluation.agent_harness.schemas import HarnessCaseResult


def _assertion_rate(results: list[HarnessCaseResult], name: str) -> float:
    values = []
    for result in results:
        matches = [item.passed for item in result.assertions if item.name == name]
        if matches:
            values.extend(matches)
    return sum(1 for item in values if item) / len(values) if values else 1.0


def _has_partial_recovery(result: HarnessCaseResult) -> bool | None:
    status = str(result.final_status or "")
    orchestration = result.result.get("orchestration") if isinstance(result.result, dict) else {}
    if status == "partially_completed":
        return bool(result.result.get("success"))
    if isinstance(orchestration, dict) and orchestration.get("execution_status") == "partially_completed":
        return bool(orchestration.get("success", result.result.get("success")))
    return None


def compute_metrics(results: list[HarnessCaseResult]) -> dict[str, Any]:
    if not results:
        return {
            "case_pass_rate": 0.0,
            "tool_selection_accuracy": 0.0,
            "dependency_resolution_rate": 0.0,
            "state_transition_pass_rate": 0.0,
            "source_trace_rate": 0.0,
            "source_quality_rate": 0.0,
            "answer_quality_rate": 0.0,
            "business_rule_pass_rate": 0.0,
            "partial_failure_recovery_rate": 0.0,
            "confirmation_safety_rate": 0.0,
            "idempotency_pass_rate": 0.0,
            "replan_limit_pass_rate": 0.0,
            "agent_composite_score": 0.0,
            "average_latency": 0.0,
        }
    partial_values = [value for value in (_has_partial_recovery(result) for result in results) if value is not None]
    tool_score = (
        _assertion_rate(results, "required_tools") + _assertion_rate(results, "forbidden_tools")
    ) / 2
    state_score = _assertion_rate(results, "state_transitions_recorded")
    source_score = (_assertion_rate(results, "source_trace") + _assertion_rate(results, "evidence_quality")) / 2
    answer_score = _assertion_rate(results, "answer_quality")
    safety_score = (
        _assertion_rate(results, "confirmation_required_boundary")
        + _assertion_rate(results, "duplicate_confirmation_safe")
        + _assertion_rate(results, "business_rule_safety")
    ) / 3
    composite = (
        0.15 * tool_score
        + 0.15 * state_score
        + 0.25 * source_score
        + 0.20 * answer_score
        + 0.25 * safety_score
    )
    return {
        "case_pass_rate": sum(1 for result in results if result.passed) / len(results),
        "tool_selection_accuracy": tool_score,
        "dependency_resolution_rate": _assertion_rate(results, "required_tools"),
        "state_transition_pass_rate": state_score,
        "source_trace_rate": _assertion_rate(results, "source_trace"),
        "source_quality_rate": _assertion_rate(results, "evidence_quality"),
        "answer_quality_rate": answer_score,
        "business_rule_pass_rate": _assertion_rate(results, "business_rule_safety"),
        "partial_failure_recovery_rate": (
            sum(1 for value in partial_values if value) / len(partial_values)
            if partial_values
            else 1.0
        ),
        "confirmation_safety_rate": _assertion_rate(results, "confirmation_required_boundary"),
        "idempotency_pass_rate": _assertion_rate(results, "duplicate_confirmation_safe"),
        "replan_limit_pass_rate": _assertion_rate(results, "replan_limit"),
        "agent_composite_score": composite,
        "agent_composite_weights": {"tool": 0.15, "state": 0.15, "source": 0.25, "answer": 0.20, "safety": 0.25},
        "average_latency": mean(result.latency_seconds for result in results),
    }
