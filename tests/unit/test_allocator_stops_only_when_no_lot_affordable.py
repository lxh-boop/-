from portfolio.target_weight_allocator import allocate_target_weights


def test_allocator_stops_only_when_no_lot_affordable() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.10, "current_price": 3.0},
            {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.80, "target_weight": 0.10, "current_price": 4.0},
        ],
        total_assets=5000,
        cash=5000,
        max_single_position=0.80,
        min_cash_ratio=0.0,
    )

    min_next_lot = min(item.one_lot_total_cost for item in allocations if item.price > 0)

    assert diagnostics.unavoidable_residual_cash < min_next_lot

