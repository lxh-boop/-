from __future__ import annotations

from strategies.binding_repository import StrategyBindingRepository
from strategy_binding_test_utils import (
    binding_service,
    confirm_binding,
    create_binding_plan,
    register_strategy,
)


def test_binding_rollback_requires_separate_confirmation(tmp_path) -> None:
    first_manifest = register_strategy(tmp_path)
    first = confirm_binding(
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
    service = binding_service(tmp_path)
    plan = service.create_rollback_plan(
        user_id="u1",
        account_id="paper_u1",
        conversation_id="conv_1",
        run_id="run_rollback",
    )
    before = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    ).list_history(
        user_id="u1",
        account_id="paper_u1",
    )
    result = service.commit(
        user_id="u1",
        plan_id=plan.data["plan_id"],
        confirmation_token=plan.data["confirmation_token"],
        conversation_id="conv_1",
    )
    after = StrategyBindingRepository(
        tmp_path / "agent_quant.db"
    ).list_history(
        user_id="u1",
        account_id="paper_u1",
    )

    assert plan.requires_confirmation
    assert len(before) == 2
    assert result.success
    assert len(after) == 3
    assert result.data["binding"]["strategy_id"] == first_manifest["strategy_id"]
    assert first.data["binding"]["binding_id"] in {
        item.binding_id for item in after
    }
