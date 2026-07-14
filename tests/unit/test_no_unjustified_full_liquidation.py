from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_no_unjustified_full_liquidation_for_short_holding() -> None:
    account = create_default_account("u1", initial_cash=100000)
    position = create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    plan = build_rebalance_plan(
        "u1",
        "2026-04-02",
        [{"stock_code": "000001", "rank": 10, "final_action": "hold", "target_weight": 0, "current_price": 10, "holding_days": 2}],
        current_positions=[position],
        account=account,
        strategy_mode="hierarchical_top10",
    )
    assert all(decision.action != "sell" for decision in plan.decisions)
