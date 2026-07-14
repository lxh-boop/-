from portfolio.paper_account import create_default_account
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.schemas import RebalanceDecision, RebalancePlan


def test_zero_quantity_not_order() -> None:
    account = create_default_account("u1", 100000)
    plan = RebalancePlan(
        user_id="u1",
        trade_date="2026-04-01",
        decisions=[
            RebalanceDecision(
                stock_code="000001",
                stock_name="A",
                action="buy",
                target_weight=0.001,
                reason="too small",
                current_price=1000,
            )
        ],
        total_target_weight=0.001,
    )

    result = execute_paper_rebalance(account, [], plan)

    assert result["orders"] == []
