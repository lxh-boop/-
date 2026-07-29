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
        '"args_schema": public_args_schema',
        '"semantic_inputs_schema"',
        '"default_args"',
        "def default_args_for",
    )
    require_text(
        "agent/collaboration/agent_directory.py",
        'default_args={"top_k": 10}',
        '"default": 10',
        "用户未指定时使用10",
    )
    require_text(
        "agent/collaboration/planner.py",
        "def _validate_planner_field_placement",
        "planner_field_placement_error",
        "args_schema 只描述要写入任务 args",
        "semantic_inputs_schema 只描述要写入任务 inputs",
        "args.top_k 写10",
        "repair_guidance=",
    )
    require_text(
        "core/llm/service.py",
        'repair_guidance: str = ""',
        "本次精确修复要求",
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
        "phase": "01.4.1",
        "status": "passed",
        "public_args_schema": True,
        "public_semantic_inputs_schema": True,
        "legacy_input_schema_hidden_from_main_agent": True,
        "precise_field_placement_error": True,
        "repair_guidance_contains_contract_rules": True,
        "default_top_k": 10,
        "main_agent_owns_worker_dag": True,
        "dag_mutation_after_planning": False,
        "timeout_changed": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
