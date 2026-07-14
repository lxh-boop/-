from portfolio.trading_cost_config import TradingCostConfig, calculate_trade_cost


def test_buy_fee_calculation() -> None:
    costs = calculate_trade_cost("buy", 10000, TradingCostConfig(buy_cost_rate=0.001))

    assert costs["commission_fee"] == 10
    assert costs["total_fee"] == 10
    assert costs["net_cash_change"] == -10010

