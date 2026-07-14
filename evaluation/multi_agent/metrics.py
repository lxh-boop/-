from __future__ import annotations

from statistics import mean
from typing import Any

from agent.agent_protocol import AGENT_OUTPUT_FIELDS
from agent.agent_specs import (
    MARKET_INTELLIGENCE,
    PORTFOLIO_ANALYSIS,
    REPORTING,
    SUPERVISOR,
    validate_tool_allowed,
)
from evaluation.multi_agent.schemas import BenchmarkRunResult, MultiAgentScenario, MULTI_AGENT_MODE


METRIC_DEFINITIONS: dict[str, str] = {
    "task_success_rate": "successful task_results divided by total task_results; deterministic task success uses result.success=true.",
    "role_handoff_completion_rate": "completed expected Supervisor -> Market -> Portfolio -> Report handoff edges divided by expected edges for multi-agent scenarios.",
    "tool_permission_violation_count": "count of actual agent_role/tool calls and declared permission probes rejected by agent_specs.validate_tool_allowed().",
    "structured_output_valid_rate": "rate of runs whose mode-specific structured output contract is valid; multi-agent requires AgentOutput fields and message_id/status.",
    "evidence_source_coverage": "per-run source count divided by expected_min_sources, capped at 1.0; scenarios with no source requirement count as 1.0.",
    "partial_failure_recovery_rate": "among scenarios tagged partial_failure_expected/tool_failure/missing_data, rate where the run still succeeds or reaches partially_completed.",
    "average_latency_seconds": "mean wall-clock seconds measured around each path execution.",
    "average_tool_call_count": "mean number of recorded tool calls per run.",
    "route_accuracy": "rate of runs whose observed supervisor decision_source matches the scenario expectation when provided.",
    "safety_route_accuracy": "rate of runs that preserve safety routing: no permission violations and protected writes are not executed by planner/replan.",
    "unnecessary_llm_planner_rate": "among runs expected not to call the LLM planner, rate where llm_planner_called is true.",
    "semantic_observer_trigger_rate": "rate of runs whose gated semantic observer was triggered.",
    "replan_success_rate": "among runs with replan_triggered, rate where the run succeeds or partially completes.",
    "invalid_replan_block_count": "count of candidate replan tasks rejected by restricted replan validation.",
    "average_llm_planner_elapsed_ms": "mean measured LLM planner latency in milliseconds; zero when planner was not called.",
    "average_llm_planner_token_estimate": "mean estimated planner token budget consumption.",
}


EXPECTED_ROLES = [SUPERVISOR, MARKET_INTELLIGENCE, PORTFOLIO_ANALYSIS, REPORTING]


def collect_errors(value: Any) -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "errors" and isinstance(child, list):
                errors.extend(str(item) for item in child if str(item).strip())
            else:
                errors.extend(collect_errors(child))
    elif isinstance(value, list):
        for child in value:
            errors.extend(collect_errors(child))
    return list(dict.fromkeys(errors))


def task_counts(task_results: dict[str, Any]) -> tuple[int, int]:
    total = len(task_results)
    succeeded = sum(1 for item in task_results.values() if isinstance(item, dict) and bool(item.get("success")))
    return total, succeeded


def source_count(task_results: dict[str, Any], agent_outputs: dict[str, Any]) -> int:
    ids: set[str] = set()

    def add_record(record: Any) -> None:
        if not isinstance(record, dict):
            return
        for key in ("chunk_id", "news_id", "source_id", "database_record_id", "stock_code", "code"):
            value = record.get(key)
            if value not in ("", None):
                ids.add(f"{key}:{value}")
                return

    for result in task_results.values():
        if not isinstance(result, dict):
            continue
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        for key in ("records", "events", "chunks", "items"):
            rows = data.get(key) or []
            if isinstance(rows, list):
                for row in rows:
                    if key == "items" and isinstance(row, dict):
                        nested = row.get("data") if isinstance(row.get("data"), dict) else {}
                        for nested_key in ("records", "events", "chunks"):
                            for nested_row in nested.get(nested_key) or []:
                                add_record(nested_row)
                    add_record(row)

    for output in agent_outputs.values():
        if not isinstance(output, dict):
            continue
        for key in ("sources", "evidence"):
            rows = output.get(key) or []
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and isinstance(row.get("record"), dict):
                        add_record(row.get("record"))
                    add_record(row)
    return len(ids)


def permission_violations(
    scenario: MultiAgentScenario,
    *,
    mode: str,
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        role = str(call.get("agent_role") or "")
        tool_name = str(call.get("tool_name") or "")
        if not role or not tool_name:
            continue
        try:
            validate_tool_allowed(role, tool_name)
        except PermissionError as exc:
            violations.append({"role": role, "tool_name": tool_name, "reason": str(exc), "source": "actual_tool_call"})

    if mode == MULTI_AGENT_MODE:
        for check in scenario.permission_checks:
            try:
                validate_tool_allowed(check.role, check.tool_name)
            except PermissionError as exc:
                violations.append(
                    {
                        "role": check.role,
                        "tool_name": check.tool_name,
                        "reason": check.reason or str(exc),
                        "source": "declared_permission_probe",
                    }
                )
    return violations


def handoff_counts(
    scenario: MultiAgentScenario,
    *,
    mode: str,
    role_timeline: list[dict[str, Any]],
) -> tuple[int, int, int]:
    if mode != MULTI_AGENT_MODE or not scenario.expect_multi_agent_path:
        return 0, 0, 0
    by_role = {str(item.get("role") or ""): item for item in role_timeline if isinstance(item, dict)}
    expected = [
        (SUPERVISOR, "user", MARKET_INTELLIGENCE),
        (MARKET_INTELLIGENCE, SUPERVISOR, PORTFOLIO_ANALYSIS),
        (PORTFOLIO_ANALYSIS, MARKET_INTELLIGENCE, REPORTING),
        (REPORTING, PORTFOLIO_ANALYSIS, "user"),
    ]
    completed = 0
    for role, handoff_from, handoff_to in expected:
        item = by_role.get(role) or {}
        if (
            item.get("message_id")
            and str(item.get("handoff_from") or "") == handoff_from
            and str(item.get("handoff_to") or "") == handoff_to
        ):
            completed += 1
    expected_count = len(expected)
    missing = expected_count - completed
    return expected_count, completed, missing


def structured_output_errors(
    scenario: MultiAgentScenario,
    *,
    mode: str,
    raw_result: dict[str, Any],
    task_results: dict[str, Any],
    tool_calls: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if mode != MULTI_AGENT_MODE:
        if not isinstance(task_results, dict):
            errors.append("direct_task_results_missing")
        if not isinstance(tool_calls, list):
            errors.append("direct_tool_calls_missing")
        if not raw_result.get("execution_status"):
            errors.append("direct_execution_status_missing")
        return errors

    if not scenario.expect_multi_agent_path:
        orchestration = raw_result.get("orchestration") if isinstance(raw_result.get("orchestration"), dict) else {}
        if orchestration.get("multi_agent"):
            errors.append("single_intent_unexpected_multi_agent")
        if not raw_result.get("intent") and not raw_result.get("execution_status"):
            errors.append("single_intent_result_missing_intent_or_status")
        return errors

    missing_roles = [role for role in EXPECTED_ROLES if role not in agent_outputs]
    if missing_roles:
        errors.append("missing_agent_outputs:" + ",".join(missing_roles))
    for role, output in agent_outputs.items():
        if not isinstance(output, dict):
            errors.append(f"agent_output_not_object:{role}")
            continue
        if not output.get("message_id"):
            errors.append(f"missing_message_id:{role}")
        if not output.get("status"):
            errors.append(f"missing_status:{role}")
        for field in AGENT_OUTPUT_FIELDS:
            if field not in output:
                errors.append(f"missing_field:{role}:{field}")
    return errors


def aggregate_metrics(results: list[BenchmarkRunResult]) -> dict[str, Any]:
    if not results:
        return {
            "task_success_rate": 0.0,
            "role_handoff_completion_rate": 0.0,
            "tool_permission_violation_count": 0,
            "structured_output_valid_rate": 0.0,
            "evidence_source_coverage": 0.0,
            "partial_failure_recovery_rate": 0.0,
            "average_latency_seconds": 0.0,
            "average_tool_call_count": 0.0,
            "route_accuracy": 0.0,
            "safety_route_accuracy": 0.0,
            "unnecessary_llm_planner_rate": 0.0,
            "semantic_observer_trigger_rate": 0.0,
            "replan_success_rate": 0.0,
            "invalid_replan_block_count": 0,
            "average_llm_planner_elapsed_ms": 0.0,
            "average_llm_planner_token_estimate": 0.0,
        }
    task_total = sum(item.task_count for item in results)
    task_success = sum(item.successful_task_count for item in results)
    handoff_expected = sum(item.handoff_expected_count for item in results)
    handoff_completed = sum(item.handoff_completed_count for item in results)
    partial = [item for item in results if item.partial_failure_expected]
    replan_runs = [item for item in results if item.replan_triggered]
    no_llm_expected = [
        item
        for item in results
        if item.raw_result
        and (
            item.raw_result.get("expect_llm_planner_called") is False
            or (item.raw_result.get("scenario") or {}).get("expect_llm_planner_called") is False
        )
    ]
    return {
        "task_success_rate": task_success / task_total if task_total else 0.0,
        "role_handoff_completion_rate": handoff_completed / handoff_expected if handoff_expected else 0.0,
        "tool_permission_violation_count": sum(item.permission_violation_count for item in results),
        "structured_output_valid_rate": sum(1 for item in results if item.structured_output_valid) / len(results),
        "evidence_source_coverage": mean(item.evidence_source_coverage for item in results),
        "partial_failure_recovery_rate": (
            sum(1 for item in partial if item.partial_failure_recovered) / len(partial)
            if partial
            else 1.0
        ),
        "average_latency_seconds": mean(item.latency_seconds for item in results),
        "average_tool_call_count": mean(item.tool_call_count for item in results),
        "route_accuracy": sum(1 for item in results if item.route_correct) / len(results),
        "safety_route_accuracy": sum(1 for item in results if item.safety_route_correct) / len(results),
        "unnecessary_llm_planner_rate": (
            sum(1 for item in no_llm_expected if item.llm_planner_called) / len(no_llm_expected)
            if no_llm_expected
            else 0.0
        ),
        "semantic_observer_trigger_rate": sum(1 for item in results if item.semantic_observer_triggered) / len(results),
        "replan_success_rate": (
            sum(1 for item in replan_runs if item.replan_success) / len(replan_runs)
            if replan_runs
            else 1.0
        ),
        "invalid_replan_block_count": sum(item.invalid_replan_block_count for item in results),
        "average_llm_planner_elapsed_ms": mean(item.llm_planner_elapsed_ms for item in results),
        "average_llm_planner_token_estimate": mean(item.llm_planner_token_estimate for item in results),
    }


def metrics_by_mode(results: list[BenchmarkRunResult]) -> dict[str, Any]:
    modes = sorted({item.mode for item in results})
    return {mode: aggregate_metrics([item for item in results if item.mode == mode]) for mode in modes}
