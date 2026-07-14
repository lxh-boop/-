from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_minimum_holding_period_blocks_unjustified_full_sell() -> None:
    account = create_default_account("u1", initial_cash=100000)
    position = create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    candidate = {
        "stock_code": "000001",
        "rank": 1,
        "final_action": "hold",
        "final_score": 0.4,
        "target_weight": 0.0,
        "current_price": 10,
        "holding_days": 1,
    }
    plan = build_rebalance_plan(
        "u1",
        "2026-04-02",
        [candidate],
        current_positions=[position],
        account=account,
        strategy_mode="hierarchical_top10",
    )
    decision = plan.decisions[0]
    assert decision.action == "hold"
    assert "minimum_holding_days=5" in decision.risk_warning
