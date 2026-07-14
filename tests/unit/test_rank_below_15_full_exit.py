from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_rank_below_15_full_exit() -> None:
    account = create_default_account("u1", 100000)
    position = create_position("u1", "000016", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1, "current_price": 10}
        for rank in range(1, 17)
    ]

    plan = build_rebalance_plan("u1", "2026-04-01", candidates, current_positions=[position], account=account, strategy_mode="hierarchical_top10")
    decision = next(item for item in plan.decisions if item.stock_code == "000016")

    assert decision.action == "sell"
    assert decision.target_weight == 0

