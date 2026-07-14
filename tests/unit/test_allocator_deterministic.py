from portfolio.target_weight_allocator import allocate_target_weights


def test_allocator_deterministic() -> None:
    candidates = [
        {"stock_code": "000002", "rank": 2, "final_action": "keep", "final_score": 0.80, "target_weight": 0.10, "current_price": 5.0},
        {"stock_code": "000001", "rank": 1, "final_action": "keep", "final_score": 0.80, "target_weight": 0.10, "current_price": 5.0},
    ]

    first, first_diag = allocate_target_weights(candidates, 10000, 10000, 0.50)
    second, second_diag = allocate_target_weights(candidates, 10000, 10000, 0.50)

    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert first_diag.to_dict() == second_diag.to_dict()

