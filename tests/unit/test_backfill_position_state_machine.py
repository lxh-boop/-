from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.schemas import RebalanceDecision, RebalancePlan


def test_backfill_position_state_machine() -> None:
    account = create_default_account("u1", 100000)
    account = account.__class__(**{**account.to_dict(), "cash": 90000, "total_assets": 100000})
    position = create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    plan = RebalancePlan(
        user_id="u1",
        trade_date="2026-05-11",
        decisions=[RebalanceDecision(stock_code="000001", stock_name="A", action="sell", target_weight=0.05, reason="reduce", current_price=10)],
        total_target_weight=0.05,
    )

    result = execute_paper_rebalance(account, [position], plan)

    assert result["positions"][0].quantity == 500

