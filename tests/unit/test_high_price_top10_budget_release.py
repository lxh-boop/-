from portfolio.target_weight_allocator import allocate_target_weights


def test_high_price_top10_budget_release_records_reason() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.05, "current_price": 200.0},
            {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.80, "target_weight": 0.20, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.50,
    )

    high_price = next(item for item in allocations if item.stock_code == "000001")

    assert high_price.released_budget > 0
    assert high_price.executable_quantity == 0
    assert diagnostics.redistributed_cash > 0

