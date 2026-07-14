from portfolio.target_weight_allocator import allocate_target_weights
from portfolio.trading_cost_config import TradingCostConfig


def test_residual_cash_includes_fees_in_one_lot_cost() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 1.0, "current_price": 10.0},
        ],
        total_assets=1100,
        cash=1100,
        max_single_position=1.0,
        min_cash_ratio=0.0,
        trading_cost_config=TradingCostConfig(buy_cost_rate=0.20),
    )

    assert allocations[0].one_lot_total_cost == 1200
    assert allocations[0].executable_quantity == 0
    assert diagnostics.executable_order_count == 0

