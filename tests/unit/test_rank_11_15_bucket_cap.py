from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_rank_11_15_bucket_cap() -> None:
    account = create_default_account("u1", 100000)
    positions = [
        create_position("u1", f"{rank:06d}", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
        for rank in range(11, 16)
    ]
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1, "current_price": 10}
        for rank in range(1, 16)
    ]

    plan = build_rebalance_plan("u1", "2026-04-01", candidates, current_positions=positions, account=account, strategy_mode="hierarchical_top10")
    buffer_weight = sum(item.target_weight for item in plan.decisions if 11 <= int(item.stock_code) <= 15)

    assert buffer_weight <= 0.15 + 1e-9

