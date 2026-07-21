from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_activate_binding_writes_exact_user_account_scope(tmp_path) -> None:
    manifest = register_strategy(tmp_path)
    plan = create_binding_plan(tmp_path, manifest)
    result = confirm_binding(tmp_path, plan)
    binding = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    ).get(result.data["binding"]["binding_id"], user_id="u1")

    assert result.success
    assert binding is not None
    assert binding.user_id == "u1"
    assert binding.account_id == "paper_u1"
    assert binding.strategy_id == manifest["strategy_id"]
