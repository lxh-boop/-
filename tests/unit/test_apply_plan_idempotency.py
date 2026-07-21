from __future__ import annotations

from agent.write_gateway import execute_confirmed_plan_v2
from strategies.registry import get_strategy_registry
from strategy_apply_test_utils import apply_plan
from strategy_workflow_test_utils import database_path


def test_apply_plan_commits_only_once(tmp_path) -> None:
    _, _, plan = apply_plan(tmp_path)
    kwargs = {
        "conversation_id": "conv_1",
        "run_id": "run_gateway",
        "db_path": database_path(tmp_path),
        "output_dir": tmp_path / "outputs",
    }
    first = execute_confirmed_plan_v2(
        plan.data["plan_id"],
        plan.data["confirmation_token"],
        "u1",
        **kwargs,
    )
    second = execute_confirmed_plan_v2(
        plan.data["plan_id"],
        plan.data["confirmation_token"],
        "u1",
        **kwargs,
    )
    matches = [
        item
        for item in get_strategy_registry(
            output_dir=tmp_path / "outputs",
            db_path=database_path(tmp_path),
        ).list(include_archived=True)
        if item.strategy_id == plan.data["strategy_id"]
        and item.version == plan.data["strategy_version"]
    ]

    assert first.success
    assert second.success is False
    assert "already_executed" in second.errors
    assert len(matches) == 1
