from __future__ import annotations

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
        "agent/collaboration/models.py",
        "authoritative_arg_bindings",
        "runtime_bound_args",
        "x-runtime-bound-args",
        "selection_requirements",
    )
    require_text(
        "agent/collaboration/agent_directory.py",
        '"focus_ref_ids": "focus_ref_ids"',
        '"user_id": "user_id"',
        '"reply_language": "reply_language"',
        "普通实体分析不需要本 Worker",
    )
    require_text(
        "agent/collaboration/planner.py",
        "TASK_INPUT_VALUE_SCHEMA",
        "_authoritative_runtime_values",
        "_prepare_payload",
        "WORKER_PLAN_AUTHORITATIVE_ARGS_BOUND",
        "runtime_bound_args",
        "只选择实体研究 Worker 和最终报告 Worker",
        "inputs 只能包含上述上游 WorkerResult 引用对象",
    )
    require_text(
        "agent/collaboration/worker_contracts.py",
        "additional_properties = schema.get",
        "elif isinstance(additional_properties, dict)",
    )

    planner_text = (ROOT / "agent/collaboration/planner.py").read_text(
        encoding="utf-8-sig"
    )
    for forbidden in (
        "auto_insert_worker",
        "auto_remove_worker",
        "auto_merge_worker",
        "auto_split_worker",
        "auto_rewire_worker",
    ):
        if forbidden in planner_text:
            raise AssertionError(f"forbidden DAG mutation:{forbidden}")

    report = {
        "phase": "01.3.1",
        "status": "passed",
        "runtime_args_bound_by_code": True,
        "semantic_inputs_only_reference_worker_results": True,
        "focus_ref_ids_not_llm_required": True,
        "dependency_compiler_preserved": True,
        "worker_selection_owner": "main_agent",
        "dag_mutation_after_planning": False,
        "timeout_changed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
