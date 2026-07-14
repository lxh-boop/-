from portfolio.hierarchical_top10_allocator import TRADE_LOT_SIZE, allocate_hierarchical_top10


def test_residual_cash_allocated_one_lot_at_a_time() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 9 + rank}
        for rank in range(1, 11)
    ]

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    assert diagnostics.redistributed_cash >= 0
    assert all(item.final_quantity % TRADE_LOT_SIZE == 0 for item in allocations)
    assert diagnostics.actual_top10_ratio <= 0.80 + 1e-9
