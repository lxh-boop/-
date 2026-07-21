from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_binding_cross_account_isolation(tmp_path) -> None:
    manifest = register_strategy(tmp_path)
    confirm_binding(
        tmp_path,
        create_binding_plan(
            tmp_path,
            manifest,
            account_id="paper_u1_a",
        ),
    )
    repository = StrategyBindingRepository(tmp_path / "agent_quant.db")

    assert repository.get_effective(
        user_id="u1",
        account_id="paper_u1_a",
    ) is not None
    assert repository.get_effective(
        user_id="u1",
        account_id="paper_u1_b",
    ) is None
