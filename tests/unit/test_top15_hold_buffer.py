from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan


def test_top15_hold_buffer_keeps_existing_position() -> None:
    account = create_default_account("u1", 100000)
    position = create_position("u1", "000012", quantity=500, cost_price=10, current_price=10, total_assets=100000)
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_score": 1 - rank / 100, "final_action": "keep", "action": "buy", "current_price": 10}
        for rank in range(1, 16)
    ]

    plan = build_rebalance_plan("u1", "2026-04-01", candidates, current_positions=[position], account=account)
    decision = next(item for item in plan.decisions if item.stock_code == "000012")

    assert decision.action == "hold"

