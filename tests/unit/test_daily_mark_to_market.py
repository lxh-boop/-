from portfolio.paper_position import create_position
from portfolio.performance_metrics import mark_to_market_positions


def test_daily_mark_to_market_updates_position_value() -> None:
    position = create_position("u1", "000001", quantity=500, cost_price=10, current_price=10, total_assets=100000)

    marked = mark_to_market_positions([position], {"000001": 12}, total_assets=100000)

    assert marked[0].current_price == 12
    assert marked[0].market_value == 6000

