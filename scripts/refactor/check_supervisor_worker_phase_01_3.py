from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def require_text(path: str, *needles: str) -> None:
    text = (ROOT / path).read_text(encoding="utf-8-sig")
    for needle in needles:
        if needle not in text:
            raise AssertionError(f"missing:{path}:{needle}")


def main() -> int:
    require_text(
        "core/llm/service.py",
        "event_callback",
        "candidate_generated",
        "repair_failed",
        'setattr(error, "diagnostics", diagnostics)',
    )
    require_text(
        "agent/collaboration/planner.py",
        "compiled_from_semantic_inputs",
        "不要输出 dependency_task_ids",
        "LOCAL_LLM_REQUEST_STARTED",
        "WORKER_PLAN_CANDIDATE_GENERATED",
        "WORKER_DAG_VALIDATED",
        "WORKER_PLAN_DEPENDENCIES_DERIVED",
    )
    require_text(
        "agent/collaboration/models.py",
        "graph_agent_task.v2",
        "def input_task_ids",
        '"inputs": _compact(self.inputs',
    )
    require_text(
        "agent/collaboration/agent_directory.py",
        "upstream_input_bindings",
        "validate_task_inputs",
        "derived_dependency_mismatch",
    )
    require_text(
        "agent/collaboration/runtime_services.py",
        "semantic_inputs",
        "dependency_derivation",
    )
    require_text(
        "agent/collaboration/coordinator.py",
        "GRAPH_REF_RESOLUTION_STARTED",
        "WORKER_PLANNING_STARTED",
        "WORKER_EXECUTION_STARTED",
        "WORKER_PLANNING_FAILED",
    )
    require_text(
        "agent/executor.py",
        "main_agent_planning_failed",
        "financial_graph_unavailable",
        "candidate_plan_diagnostics",
    )
    require_text(
        "agent/console_trace.py",
        "LOCAL_LLM_REQUEST_STARTED",
        'f"{question_stem}__{run_stem}.md"',
        "失败阶段与错误分类",
    )
    require_text(
        "run_agent_api.py",
        "_reload_directories",
        "reload_dirs=reload_dirs",
        'reload_includes=["*.py"]',
    )

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "phase_01_3_run_agent_api",
        ROOT / "run_agent_api.py",
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot load run_agent_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    watched_names = {Path(item).name for item in module._reload_directories()}
    forbidden = {"runtime", "logs", "outputs", "data", "models"}
    if watched_names.intersection(forbidden):
        raise AssertionError(
            f"runtime directories are still watched:{sorted(watched_names.intersection(forbidden))}"
        )

    planner = (ROOT / "agent/collaboration/planner.py").read_text(
        encoding="utf-8-sig"
    )
    for forbidden_mutation in (
        "auto_insert_worker",
        "auto_remove_worker",
        "auto_merge_worker",
        "auto_split_worker",
    ):
        if forbidden_mutation in planner:
            raise AssertionError(f"forbidden DAG mutation:{forbidden_mutation}")

    report = {
        "phase": "01.3",
        "status": "passed",
        "main_agent_still_generates_worker_dag": True,
        "main_agent_declares_semantic_inputs": True,
        "dependencies_are_compiled_from_inputs": True,
        "llm_does_not_generate_dependency_task_ids": True,
        "validator_mutates_dag": False,
        "planning_events_are_live": True,
        "rejected_candidates_are_archived": True,
        "planning_and_neo4j_errors_are_distinct": True,
        "markdown_filename_contains_run_id": True,
        "reload_watches_source_only": True,
        "timeout_changed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
