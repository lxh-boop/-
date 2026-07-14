from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_min_rebalance_threshold_keeps_small_delta() -> None:
    account = create_default_account("u1", 100000)
    position = create_position("u1", "000001", quantity=500, cost_price=10, current_price=10, total_assets=100000)
    candidates = [
        {
            "stock_code": "000001",
            "rank": 1,
            "final_score": 0.9,
            "final_action": "keep",
            "action": "buy",
            "target_weight": 0.055,
            "current_price": 10,
        }
    ]

    plan = build_rebalance_plan(
        "u1",
        "2026-04-01",
        candidates,
        current_positions=[position],
        account=account,
        min_rebalance_weight_delta=0.01,
    )

    assert plan.decisions[0].action == "hold"

