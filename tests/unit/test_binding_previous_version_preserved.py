from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import (
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_binding_previous_version_is_preserved_in_history(tmp_path) -> None:
    first_manifest = register_strategy(tmp_path)
    first = confirm_binding(
        tmp_path,
        create_binding_plan(tmp_path, first_manifest),
    )
    second_manifest = register_strategy(
        tmp_path,
        config={
            "entry_top_k": 7,
            "max_positions": 7,
            "target_invested_weight": 0.60,
            "minimum_cash_ratio": 0.25,
        },
    )
    second = confirm_binding(
        tmp_path,
        create_binding_plan(tmp_path, second_manifest),
    )
    repository = StrategyBindingRepository(tmp_path / "agent_quant.db")
    old = repository.get(
        first.data["binding"]["binding_id"],
        user_id="u1",
    )

    assert old is not None
    assert old.status == "replaced"
    assert (
        second.data["binding"]["previous_binding_id"]
        == old.binding_id
    )
