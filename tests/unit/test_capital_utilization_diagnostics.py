from portfolio.target_weight_allocator import allocate_target_weights


def test_capital_utilization_diagnostics() -> None:
    _, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.99, "target_weight": 0.10, "current_price": 5.0},
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.50,
    )
    data = diagnostics.to_dict()

    assert data["total_asset"] == 10000
    assert data["reserved_cash"] == 500
    assert "capital_utilization_rate" in data
    assert data["allocation_details"]

