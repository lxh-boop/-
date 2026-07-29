"""Static architecture checks for structured Worker contracts (Phase 01.1)."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def main() -> None:
    required = [
        ROOT / "agent/collaboration/worker_contracts.py",
        ROOT / "agent/collaboration/agent_directory.py",
        ROOT / "agent/collaboration/planner.py",
        ROOT / "agent/collaboration/models.py",
        ROOT / "agent/collaboration/specialist_runtime.py",
        ROOT / "tests/unit/test_supervisor_worker_phase_01_1_contracts.py",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        fail("missing files: " + ", ".join(missing))

    for path in required:
        if path.suffix == ".py":
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))

    planner = (ROOT / "agent/collaboration/planner.py").read_text(encoding="utf-8-sig")
    directory = (ROOT / "agent/collaboration/agent_directory.py").read_text(encoding="utf-8-sig")
    specialist = (ROOT / "agent/collaboration/specialist_runtime.py").read_text(encoding="utf-8-sig")

    required_planner_markers = [
        '"worker_id"',
        '"args"',
        '"expected_output_type"',
        "worker_selection_owner",
        "dag_mutation_after_planning",
        "validate_task_args",
        "required_upstream_output_groups",
    ]
    for marker in required_planner_markers:
        if marker not in planner:
            fail(f"planner marker missing: {marker}")

    forbidden_planner_markers = [
        "分析600519",
        "auto_insert_worker",
        "split_worker_task",
        "merge_worker_task",
        "replace_worker",
    ]
    for marker in forbidden_planner_markers:
        if marker in planner:
            fail(f"forbidden planner marker found: {marker}")

    for marker in [
        "input_schema=",
        "output_schema=",
        "non_responsibilities=",
        "private_tool_ids=",
        "private_worker_prompt=",
        "validate_result",
    ]:
        if marker not in directory:
            fail(f"directory contract marker missing: {marker}")

    if "validate_task_contract" not in specialist or "validate_result" not in specialist:
        fail("SpecialistRuntime is not enforcing Worker input/output contracts")

    from agent.collaboration.agent_directory import AgentDirectory

    catalog = AgentDirectory().safe_catalog()
    if len(catalog) != 7:
        fail(f"expected 7 public Worker cards, got {len(catalog)}")
    for card in catalog:
        for key in (
            "worker_id",
            "agent_id",
            "responsibility",
            "args_schema",
            "semantic_inputs_schema",
            "output_schema",
            "output_types",
            "non_responsibilities",
            "side_effects",
        ):
            if key not in card:
                fail(f"public Worker card missing {key}: {card.get('worker_id')}")
        if "private_tool_ids" in card or "private_worker_prompt" in card:
            fail(f"private Worker metadata leaked: {card.get('worker_id')}")

    print(
        json.dumps(
            {
                "phase": "01.1",
                "worker_count": len(catalog),
                "main_agent_selects_workers": True,
                "worker_dag_mutation_after_planning": False,
                "worker_args_semantic_inputs_output_schema": True,
                "private_tool_schema_visibility": "worker_only",
                "status": "passed",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
