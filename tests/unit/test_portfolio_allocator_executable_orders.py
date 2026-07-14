from portfolio.target_weight_allocator import allocate_target_weights


def test_allocator_generates_executable_order_when_candidate_is_affordable() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "stock_name": "A", "final_action": "keep", "final_score": 0.9, "target_weight": 0.08, "current_price": 5.0},
            {"stock_code": "000002", "stock_name": "B", "final_action": "keep", "final_score": 0.8, "target_weight": 0.08, "current_price": 50.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.08,
    )

    executable = [item for item in allocations if item.executable_quantity > 0]
    assert executable
    assert executable[0].stock_code == "000001"
    assert diagnostics.executable_order_count >= 1
