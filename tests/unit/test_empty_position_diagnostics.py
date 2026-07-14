from portfolio.target_weight_allocator import allocate_target_weights


def test_empty_position_diagnostics_explain_zero_orders() -> None:
    _, diagnostics = allocate_target_weights(
        [
            {"stock_code": "000001", "final_action": "keep", "final_score": 0.9, "target_weight": 0.08, "current_price": 20.0}
        ],
        total_assets=10000,
        cash=10000,
        max_single_position=0.08,
    )

    data = diagnostics.to_dict()
    assert data["candidate_count"] == 1
    assert data["positive_target_weight_count"] == 1
    assert data["valid_price_count"] == 1
    assert data["executable_order_count"] == 0
    assert any("一手" in reason for reason in data["reasons"])
