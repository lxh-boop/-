from __future__ import annotations

from pathlib import Path

from strategies.registry import StrategyRegistry
from strategy_apply_test_utils import apply_plan, apply_service


def test_apply_failure_rolls_back_files(tmp_path, monkeypatch) -> None:
    _, _, plan = apply_plan(tmp_path)

    def fail_register(self, manifest, *, allow_existing=False):
        raise RuntimeError("forced_registry_failure")

    monkeypatch.setattr(StrategyRegistry, "register", fail_register)
    result = apply_service(tmp_path).commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )

    assert result.success is False
    assert "apply_failed" in result.errors
    assert Path(plan.data["formal_target"]).exists() is False
    assert Path(plan.data["formal_target"]).parent.exists() is False
