from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.schemas import RebalancePlan


def test_position_carry_forward() -> None:
    account = create_default_account("u1", 100000)
    position = create_position("u1", "000001", quantity=1000, cost_price=10, current_price=10, total_assets=100000)
    plan = RebalancePlan(user_id="u1", trade_date="2026-05-11", decisions=[], total_target_weight=0)

    result = execute_paper_rebalance(account, [position], plan, mark_price_lookup={"000001": 11})

    assert len(result["positions"]) == 1
    assert result["positions"][0].stock_code == "000001"
    assert result["positions"][0].quantity == 1000
    assert result["positions"][0].current_price == 11

