from portfolio.target_weight_allocator import allocate_target_weights


def test_residual_cash_respects_industry_limit() -> None:
    allocations, _ = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.50, "current_price": 5.0, "industry": "bank"},
            {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.98, "target_weight": 0.50, "current_price": 5.0, "industry": "bank"},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.50,
        max_industry_position=0.10,
        min_cash_ratio=0.0,
    )

    industry_value = sum(item.executable_target_amount for item in allocations)

    assert industry_value <= 1000

