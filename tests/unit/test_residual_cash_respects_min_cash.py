from portfolio.target_weight_allocator import allocate_target_weights


def test_residual_cash_respects_min_cash() -> None:
    _, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.90, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=1.0,
        min_cash_ratio=0.20,
    )

    assert diagnostics.reserved_cash == 2000
    assert diagnostics.actual_invested_cash <= diagnostics.planned_investable_asset

