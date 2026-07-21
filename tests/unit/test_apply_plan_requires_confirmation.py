from __future__ import annotations

from pathlib import Path

from strategies.registry import get_strategy_registry
from strategy_apply_test_utils import apply_plan
from strategy_workflow_test_utils import database_path


def test_apply_plan_requires_confirmation_and_does_not_write(tmp_path) -> None:
    _, _, plan = apply_plan(tmp_path)
    target = Path(plan.data["formal_target"])
    registry = get_strategy_registry(
        output_dir=tmp_path / "outputs",
        db_path=database_path(tmp_path),
    )

    assert plan.success
    assert plan.requires_confirmation is True
    assert plan.data["operation_type"] == "apply_strategy_implementation"
    assert target.exists() is False
    assert registry.get(
        plan.data["strategy_id"],
        plan.data["strategy_version"],
    ) is None
