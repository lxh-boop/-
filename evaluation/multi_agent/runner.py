from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.executor import _execute_readonly_multi_agent_collaboration, run_agent_request
from agent.orchestration.multi_task_executor import execute_multi_intent_plan
from evaluation.multi_agent.exporter import export_benchmark
from evaluation.multi_agent.fixtures import write_benchmark_fixture
from evaluation.multi_agent.metrics import (
    aggregate_metrics,
    collect_errors,
    handoff_counts,
    metrics_by_mode,
    permission_violations,
    source_count,
    structured_output_errors,
    task_counts,
)
from evaluation.multi_agent.scenarios import default_scenarios
from evaluation.multi_agent.schemas import (
    BenchmarkRunResult,
    DIRECT_MODE,
    MULTI_AGENT_MODE,
    MultiAgentScenario,
)


def _safe_status(value: dict[str, Any]) -> str:
    return str(
        value.get("execution_status")
        or value.get("final_status")
        or (value.get("runtime") or {}).get("status")
        or ""
    )


def _run_direct_path(
    scenario: MultiAgentScenario,
    *,
    user_id: str,
    output_dir: Path,
    db_path: Path,
    top_k: int,
) -> dict[str, Any]:
    return execute_multi_intent_plan(
        {"tasks": scenario.tasks},
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
        default_top_k=top_k,
        session_id=f"benchmark_{scenario.scenario_id}_direct",
        language="en",
        context={"benchmark_mode": DIRECT_MODE},
    )


def _run_multi_agent_path(
    scenario: MultiAgentScenario,
    *,
    user_id: str,
    output_dir: Path,
    db_path: Path,
    top_k: int,
) -> dict[str, Any]:
    if not scenario.expect_multi_agent_path:
        return run_agent_request(
            scenario.query,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            top_k=top_k,
            session_id=f"benchmark_{scenario.scenario_id}_compat",
            reply_language="en",
            llm_api_key="",
        )

    return _execute_readonly_multi_agent_collaboration(
        query=scenario.query,
        decomposition={
            "query": scenario.query,
            "tasks": scenario.tasks,
            "is_multi_intent": True,
        },
        user_id=user_id,
        output_dir=output_dir,
        db_path=db_path,
        default_top_k=top_k,
        session_id=f"benchmark_{scenario.scenario_id}_multi_agent",
        language="en",
        context={"benchmark_mode": MULTI_AGENT_MODE},
    )


def _normalise_raw(
    raw: dict[str, Any],
    *,
    mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    orchestration = raw.get("orchestration") if isinstance(raw.get("orchestration"), dict) else raw
    task_results = dict(orchestration.get("task_results") or {})
    tool_calls = list(orchestration.get("tool_calls") or raw.get("tool_calls") or [])
    role_timeline = list(orchestration.get("agent_timeline") or [])
    agent_outputs = dict(orchestration.get("agent_outputs") or {})
    if mode == MULTI_AGENT_MODE and raw.get("orchestration"):
        task_results = dict((raw.get("orchestration") or {}).get("task_results") or {})
        tool_calls = list((raw.get("orchestration") or {}).get("tool_calls") or raw.get("tool_calls") or [])
        role_timeline = list((raw.get("orchestration") or {}).get("agent_timeline") or [])
        agent_outputs = dict((raw.get("orchestration") or {}).get("agent_outputs") or {})
    return task_results, tool_calls, role_timeline, agent_outputs


def _walk_observations(value: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(value, dict):
        observations = value.get("observations")
        if isinstance(observations, list):
            for row in observations:
                if isinstance(row, dict):
                    rows.append(row)
                    rows.extend(_walk_observations(row.get("child_observations")))
        else:
            rows.extend(_walk_observations(value.get("orchestration")))
    elif isinstance(value, list):
        for item in value:
            rows.extend(_walk_observations(item))
    return rows


def _semantic_observer_triggered(raw: dict[str, Any]) -> bool:
    for row in _walk_observations(raw):
        observer = row.get("semantic_observer")
        if isinstance(observer, dict) and observer.get("triggered"):
            return True
    return False


def _supervisor_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    decomposition = raw.get("decomposition") if isinstance(raw.get("decomposition"), dict) else {}
    diagnostics = decomposition.get("diagnostics") if isinstance(decomposition.get("diagnostics"), dict) else {}
    decision = (
        decomposition.get("supervisor_decision")
        if isinstance(decomposition.get("supervisor_decision"), dict)
        else {}
    )
    runtime = raw.get("runtime") if isinstance(raw.get("runtime"), dict) else {}
    if not decision and isinstance(runtime.get("supervisor_decision"), dict):
        decision = runtime.get("supervisor_decision") or {}
    return {
        "decision_source": str(decision.get("decision_source") or diagnostics.get("decision_source") or ""),
        "llm_planner_called": bool(diagnostics.get("llm_planner_called") or runtime.get("llm_planner_called")),
        "llm_planner_elapsed_ms": float(diagnostics.get("llm_planner_elapsed_ms") or 0.0),
        "llm_planner_token_estimate": int(diagnostics.get("llm_planner_token_estimate") or 0),
    }


def _result_from_raw(
    scenario: MultiAgentScenario,
    *,
    mode: str,
    raw: dict[str, Any],
    latency_seconds: float,
    output_dir: Path,
    db_path: Path,
) -> BenchmarkRunResult:
    task_results, tool_calls, role_timeline, agent_outputs = _normalise_raw(raw, mode=mode)
    task_total, task_success = task_counts(task_results)
    violations = permission_violations(scenario, mode=mode, tool_calls=tool_calls)
    expected_handoff, completed_handoff, missing_handoff = handoff_counts(
        scenario,
        mode=mode,
        role_timeline=role_timeline,
    )
    output_errors = structured_output_errors(
        scenario,
        mode=mode,
        raw_result=raw,
        task_results=task_results,
        tool_calls=tool_calls,
        agent_outputs=agent_outputs,
    )
    sources = source_count(task_results, agent_outputs)
    expected_sources = int(scenario.expected_min_sources or 0)
    source_coverage = 1.0 if expected_sources <= 0 else min(1.0, sources / expected_sources)
    status = _safe_status(raw)
    success = bool(raw.get("success")) if "success" in raw else status in {"completed", "partially_completed"}
    partial_expected = bool({"partial_failure_expected", "tool_failure", "missing_data"} & set(scenario.tags))
    partial_recovered = None
    if partial_expected:
        partial_recovered = bool(success or status == "partially_completed")
    supervisor = _supervisor_metrics(raw)
    decision_source = supervisor["decision_source"]
    expected_source = str(scenario.expected_decision_source or "")
    route_correct = True if mode == DIRECT_MODE else (not expected_source or decision_source == expected_source)
    llm_expected = scenario.expect_llm_planner_called
    if mode != DIRECT_MODE and llm_expected is not None:
        route_correct = route_correct and supervisor["llm_planner_called"] == bool(llm_expected)
    semantic_triggered = _semantic_observer_triggered(raw)
    if mode != DIRECT_MODE and scenario.expect_semantic_observer is not None:
        route_correct = route_correct and semantic_triggered == bool(scenario.expect_semantic_observer)
    replan_count = int(
        raw.get("replan_count")
        or (raw.get("orchestration") or {}).get("replan_count")
        or 0
    )
    replan_triggered = replan_count > 0
    if mode != DIRECT_MODE and scenario.expect_replan is not None:
        route_correct = route_correct and replan_triggered == bool(scenario.expect_replan)
    invalid_replan_block_count = int(
        raw.get("invalid_replan_block_count")
        or (raw.get("orchestration") or {}).get("invalid_replan_block_count")
        or 0
    )
    actual_permission_violations = [
        item
        for item in violations
        if str(item.get("source") or "") == "actual_tool_call"
    ]
    safety_route_correct = len(actual_permission_violations) == 0 and invalid_replan_block_count >= 0
    raw_with_expectations = {
        **raw,
        "scenario": scenario.to_dict(),
        "expect_llm_planner_called": scenario.expect_llm_planner_called,
    }

    return BenchmarkRunResult(
        scenario_id=scenario.scenario_id,
        scenario_name=scenario.name,
        mode=mode,
        success=success,
        execution_status=status,
        latency_seconds=round(latency_seconds, 4),
        task_count=task_total,
        successful_task_count=task_success,
        tool_call_count=len(tool_calls),
        permission_violation_count=len(violations),
        permission_violations=violations,
        structured_output_valid=not output_errors,
        structured_output_errors=output_errors,
        handoff_expected_count=expected_handoff,
        handoff_completed_count=completed_handoff,
        missing_handoff_count=missing_handoff,
        evidence_source_count=sources,
        evidence_source_coverage=round(source_coverage, 4),
        partial_failure_expected=partial_expected,
        partial_failure_recovered=partial_recovered,
        decision_source=decision_source,
        route_correct=route_correct,
        safety_route_correct=safety_route_correct,
        llm_planner_called=bool(supervisor["llm_planner_called"]),
        llm_planner_elapsed_ms=float(supervisor["llm_planner_elapsed_ms"]),
        llm_planner_token_estimate=int(supervisor["llm_planner_token_estimate"]),
        semantic_observer_triggered=semantic_triggered,
        replan_triggered=replan_triggered,
        replan_success=(bool(success or status == "partially_completed") if replan_triggered else None),
        invalid_replan_block_count=invalid_replan_block_count,
        errors=collect_errors(raw),
        warnings=[str(item) for item in (raw.get("warnings") or [])],
        tool_calls=tool_calls,
        role_timeline=role_timeline,
        agent_outputs=agent_outputs,
        raw_result=raw_with_expectations,
        output_dir=str(output_dir),
        db_path=str(db_path),
    )


def run_scenario(
    scenario: MultiAgentScenario,
    *,
    output_root: str | Path,
    user_id: str = "benchmark_user",
    top_k: int = 10,
) -> list[BenchmarkRunResult]:
    results: list[BenchmarkRunResult] = []
    for mode in (DIRECT_MODE, MULTI_AGENT_MODE):
        case_dir = Path(output_root) / "cases" / scenario.scenario_id / mode
        db_path = case_dir / "agent_quant.db"
        write_benchmark_fixture(
            output_dir=case_dir,
            db_path=db_path,
            user_id=user_id,
            setup=scenario.fixture,
        )
        started = time.perf_counter()
        if mode == DIRECT_MODE:
            raw = _run_direct_path(
                scenario,
                user_id=user_id,
                output_dir=case_dir,
                db_path=db_path,
                top_k=top_k,
            )
        else:
            raw = _run_multi_agent_path(
                scenario,
                user_id=user_id,
                output_dir=case_dir,
                db_path=db_path,
                top_k=top_k,
            )
        elapsed = time.perf_counter() - started
        results.append(
            _result_from_raw(
                scenario,
                mode=mode,
                raw=raw,
                latency_seconds=elapsed,
                output_dir=case_dir,
                db_path=db_path,
            )
        )
    return results


def default_output_dir() -> Path:
    return Path("outputs") / "multi_agent_benchmark" / datetime.now().strftime("%Y%m%d_%H%M%S")


def run_benchmark(
    *,
    output_dir: str | Path | None = None,
    scenarios: list[MultiAgentScenario] | None = None,
    user_id: str = "benchmark_user",
    top_k: int = 10,
    export: bool = True,
) -> dict[str, Any]:
    scenario_list = list(scenarios or default_scenarios())
    output_root = Path(output_dir) if output_dir else default_output_dir()
    output_root.mkdir(parents=True, exist_ok=True)
    results: list[BenchmarkRunResult] = []
    for scenario in scenario_list:
        results.extend(run_scenario(scenario, output_root=output_root, user_id=user_id, top_k=top_k))

    payload: dict[str, Any] = {
        "config": {
            "scenario_count": len(scenario_list),
            "run_count": len(results),
            "modes": [DIRECT_MODE, MULTI_AGENT_MODE],
            "output_dir": str(output_root),
            "uses_temp_fixture_data": True,
            "write_tools_executed": False,
        },
        "scenarios": [item.to_dict() for item in scenario_list],
        "metrics": aggregate_metrics(results),
        "metrics_by_mode": metrics_by_mode(results),
        "results": [item.to_dict() for item in results],
    }
    if export:
        payload["artifacts"] = export_benchmark(output_root=output_root, payload=payload, results=results)
    return payload
