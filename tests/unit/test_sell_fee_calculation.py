from portfolio.trading_cost_config import TradingCostConfig, calculate_trade_cost


def test_sell_fee_calculation() -> None:
    costs = calculate_trade_cost("sell", 10000, TradingCostConfig(sell_cost_rate=0.0015))

    assert costs["commission_fee"] == 15
    assert costs["total_fee"] == 15
    assert costs["net_cash_change"] == 9985

