from portfolio.target_weight_allocator import allocate_target_weights, round_a_share_quantity


def test_a_share_lot_size_rounds_to_100() -> None:
    assert round_a_share_quantity(199, lot_size=100) == 100
    assert round_a_share_quantity(99, lot_size=100) == 0


def test_unaffordable_lot_records_reason_and_tries_next_candidate() -> None:
    allocations, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "final_action": "keep", "final_score": 0.9, "target_weight": 0.08, "current_price": 20.0},
            {"stock_code": "000002", "final_action": "keep", "final_score": 0.8, "target_weight": 0.08, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.08,
    )

    assert allocations[0].executable_quantity == 0
    assert "一手" in allocations[0].cannot_execute_reason
    assert any(item.stock_code == "000002" and item.executable_quantity > 0 for item in allocations)
    assert diagnostics.affordable_lot_count == 1
