"""Use the configured local LLM to test MainAgent Worker selection after Phase 01.1."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.planner import CoordinatorPlanner
from agent.graph.contracts import GraphNodeKind, GraphRef
from core.llm import LLMService, resolve_active_llm_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _check(
    checks: dict[str, bool],
    key: str,
    condition: Any,
) -> None:
    checks[key] = bool(condition)


def main() -> int:
    args = parse_args()
    settings = resolve_active_llm_settings(mode="local")
    service = LLMService(settings=settings)
    if not service.is_available:
        raise RuntimeError("local_llm_profile_is_not_configured")

    planner = CoordinatorPlanner(AgentDirectory(), llm_service=service)
    focus_ref = GraphRef(
        graph_id="financial_graph",
        node_id="object:security:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        source="phase_01_1_local_llm_acceptance",
        confidence=1.0,
        locked=True,
    )

    started = time.perf_counter()
    tasks, metadata = planner.plan(
        query="分析600519",
        request_mode="analysis",
        session_id="phase-01-1-local-llm-session",
        run_id="phase-01-1-local-llm-run",
        user_id="cht",
        focus_refs=[focus_ref],
        context_refs=[],
        memory_summary="",
        language="zh",
    )
    duration = round(time.perf_counter() - started, 3)

    actual_worker_ids = [task.worker_id for task in tasks]
    expected_worker_ids = ["W01", "W06"]
    checks: dict[str, bool] = {}

    _check(checks, "exact_worker_sequence", actual_worker_ids == expected_worker_ids)
    _check(checks, "exact_task_count", len(tasks) == 2)

    if len(tasks) == 2:
        research_task = tasks[0]
        report_task = tasks[1]

        # Task IDs are generated dynamically. Validate the real relationship
        # instead of requiring a fixed task ID such as "task_1".
        _check(
            checks,
            "report_depends_on_research_task",
            report_task.dependency_task_ids == [research_task.task_id],
        )
        _check(
            checks,
            "report_inputs_reference_research_task",
            report_task.input_task_ids("upstream_results") == [research_task.task_id],
        )
        _check(
            checks,
            "research_output_contract",
            research_task.expected_output_type == "EntityResearchResult",
        )
        _check(
            checks,
            "report_output_contract",
            report_task.expected_output_type == "FinalReport",
        )
        _check(
            checks,
            "research_focus_ref",
            "object:security:600519"
            in list(research_task.args.get("focus_ref_ids") or []),
        )
        _check(
            checks,
            "worker_ids_are_present",
            bool(research_task.worker_id) and bool(report_task.worker_id),
        )
    else:
        for key in (
            "report_depends_on_research_task",
            "report_inputs_reference_research_task",
            "research_output_contract",
            "report_output_contract",
            "research_focus_ref",
            "worker_ids_are_present",
        ):
            checks[key] = False

    _check(
        checks,
        "main_agent_owns_worker_selection",
        metadata.get("worker_selection_owner") == "main_agent",
    )
    _check(
        checks,
        "dag_mutation_forbidden",
        metadata.get("dag_mutation_after_planning") == "forbidden",
    )
    _check(
        checks,
        "structured_worker_contract_enabled",
        metadata.get("structured_worker_contract") is True,
    )
    _check(
        checks,
        "no_fallback_used",
        metadata.get("fallback_used") is False,
    )

    passed = all(checks.values())
    failed_checks = [key for key, value in checks.items() if not value]

    report = {
        "status": "passed" if passed else "failed",
        "query": "分析600519",
        "expected_worker_ids": expected_worker_ids,
        "actual_worker_ids": actual_worker_ids,
        "duration_seconds": duration,
        "checks": checks,
        "failed_checks": failed_checks,
        "tasks": [task.safe_for_coordinator() for task in tasks],
        "planner_metadata": metadata,
        "model_profile": settings.profile.public_dict,
        "timeout_override_applied": False,
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
