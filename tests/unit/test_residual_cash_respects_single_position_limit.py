from portfolio.target_weight_allocator import allocate_target_weights


def test_residual_cash_respects_single_position_limit() -> None:
    allocations, _ = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.80, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.10,
        min_cash_ratio=0.0,
    )

    assert allocations[0].final_weight <= 0.10

