from portfolio.target_weight_allocator import allocate_target_weights


def test_cash_cap_exception_records_reason_when_no_lot_is_legal() -> None:
    candidates = [
        {
            "stock_code": "000001",
            "rank": 1,
            "final_action": "keep",
            "final_score": 0.9,
            "target_weight": 0.08,
            "current_price": 1000.0,
        }
    ]

    _, diagnostics = allocate_target_weights(
        candidates,
        total_assets=100000,
        cash=100000,
        max_single_position=0.08,
        max_industry_position=1.0,
    )

    assert diagnostics.cash_ratio_after_allocation > 0.30
    assert diagnostics.cash_cap_exception is True
    assert diagnostics.cash_cap_exception_reason
