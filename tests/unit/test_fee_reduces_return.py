from portfolio.paper_account import create_default_account
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.schemas import RebalanceDecision, RebalancePlan
from portfolio.trading_cost_config import TradingCostConfig


def test_fee_reduces_return_after_buy() -> None:
    account = create_default_account("u1", 100000)
    plan = RebalancePlan(
        user_id="u1",
        trade_date="2026-04-01",
        decisions=[
            RebalanceDecision(
                stock_code="000001",
                stock_name="A",
                action="buy",
                target_weight=0.1,
                reason="buy",
                current_price=10,
            )
        ],
        total_target_weight=0.1,
    )

    result = execute_paper_rebalance(
        account,
        [],
        plan,
        cost_config=TradingCostConfig(user_id="u1", buy_cost_rate=0.001),
    )

    assert result["account"].total_assets < 100000
    assert result["orders"][0].total_fee == 10

