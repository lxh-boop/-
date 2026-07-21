from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_binding_has_single_active_row_per_account(tmp_path) -> None:
    first_manifest = register_strategy(tmp_path)
    confirm_binding(
        tmp_path,
        create_binding_plan(tmp_path, first_manifest),
    )
    second_manifest = register_strategy(
        tmp_path,
        config={
            "entry_top_k": 8,
            "max_positions": 8,
            "target_invested_weight": 0.65,
            "minimum_cash_ratio": 0.20,
        },
    )
    confirm_binding(
        tmp_path,
        create_binding_plan(tmp_path, second_manifest),
    )
    history = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    ).list_history(
        user_id="u1",
        account_id="paper_u1",
    )

    assert len([item for item in history if item.status == "active"]) == 1
    assert len([item for item in history if item.status == "replaced"]) == 1
