from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_reflection_write_detection_is_structural_not_natural_language():
    source = _read("agent/reflection/critic_engine.py")
    function = source.split("def _looks_like_write_result", 1)[1].split(
        "def _risk_conflict",
        1,
    )[0]

    assert "str(summary).lower()" not in function
    assert '"requires_confirmation"' in function
    assert '"operation_type"' in function
    assert '"plan_id"' in function


def test_v2_tool_permission_audit_accepts_canonical_llm_planned_tools():
    validator = _read("agent/worker_planning/validator.py")
    executor = _read("agent/worker_planning/executor.py")

    assert "WorkerPlanValidator" in validator
    assert "worker_write_tool_forbidden" in validator
    assert "allowed_capability_ids" in _read(
        "agent/tool_runtime/contracts.py"
    )
    assert "capability_id=task.capability_id" in executor
