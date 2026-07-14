from portfolio.target_weight_allocator import allocate_target_weights


def test_residual_cash_redistribution_moves_budget_to_executable_top10() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.95, "target_weight": 0.10, "current_price": 60.0},
            {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.90, "target_weight": 0.10, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.50,
    )

    by_code = {item.stock_code: item for item in allocations}

    assert by_code["000001"].executable_quantity == 0
    assert by_code["000001"].released_budget > 0
    assert by_code["000002"].final_quantity > by_code["000002"].initial_quantity
    assert diagnostics.redistributed_cash > 0

