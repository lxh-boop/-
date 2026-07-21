from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import create_binding_plan, register_strategy


def test_activate_binding_requires_confirmation(tmp_path) -> None:
    manifest = register_strategy(tmp_path)
    plan = create_binding_plan(tmp_path, manifest)
    history = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    ).list_history(
        user_id="u1",
        account_id="paper_u1",
    )

    assert plan.success
    assert plan.requires_confirmation
    assert history == []
    assert plan.data["after_state_preview"]["changes_current_positions"] is False
