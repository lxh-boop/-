from portfolio.rebalance_rules import build_rebalance_plan
from strategy_runtime_test_utils import (
    runtime_account,
    runtime_candidates,
    runtime_position,
)


def test_hold_buffer_rank_really_changes_turnover() -> None:
    position = runtime_position(12)
    buffered = build_rebalance_plan(
        "u1",
        "2026-07-16",
        runtime_candidates(),
        current_positions=[position],
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        hold_buffer_rank=15,
    )
    narrow = build_rebalance_plan(
        "u1",
        "2026-07-16",
        runtime_candidates(),
        current_positions=[position],
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        hold_buffer_rank=10,
    )

    buffered_decision = next(
        item for item in buffered.decisions if item.stock_code == "000012"
    )
    narrow_decision = next(
        item for item in narrow.decisions if item.stock_code == "000012"
    )
    assert buffered_decision.target_weight > 0
    assert narrow_decision.action == "sell"
