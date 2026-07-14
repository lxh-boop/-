from portfolio.target_weight_allocator import allocate_target_weights
from portfolio.trading_cost_config import TradingCostConfig


def test_cash_ratio_reallocated_until_below_cap_when_legal_candidates_exist() -> None:
    candidates = [
        {
            "stock_code": f"00000{i}",
            "rank": i,
            "final_action": "keep",
            "final_score": 1.0 - i * 0.01,
            "confidence": 0.9,
            "target_weight": 0.08,
            "current_price": 10.0,
        }
        for i in range(1, 11)
    ]

    _, diagnostics = allocate_target_weights(
        candidates,
        total_assets=100000,
        cash=100000,
        max_single_position=0.08,
        max_industry_position=1.0,
        trading_cost_config=TradingCostConfig(user_id="u1"),
    )

    assert diagnostics.cash_ratio_after_allocation <= diagnostics.maximum_cash_ratio
    assert diagnostics.cash_cap_exception is False
    assert diagnostics.actual_invested_cash > 70000
