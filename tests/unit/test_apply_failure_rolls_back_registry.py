from __future__ import annotations

from pathlib import Path

from strategies.registry import get_strategy_registry
from strategy_apply_test_utils import apply_plan, apply_service
from strategy_workflow_test_utils import database_path


def test_apply_failure_rolls_back_registry(tmp_path, monkeypatch) -> None:
    _, _, plan = apply_plan(tmp_path)
    service = apply_service(tmp_path)

    def fail_status_update(*args, **kwargs):
        raise RuntimeError("forced_status_failure")

    monkeypatch.setattr(
        service.implementations.repository,
        "update_implementation",
        fail_status_update,
    )
    result = service.commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )
    registry = get_strategy_registry(
        output_dir=tmp_path / "outputs",
        db_path=database_path(tmp_path),
    )

    assert result.success is False
    assert registry.get(
        plan.data["strategy_id"],
        plan.data["strategy_version"],
    ) is None
    assert Path(plan.data["formal_target"]).exists() is False
