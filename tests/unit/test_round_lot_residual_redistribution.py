from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_round_lot_residual_redistribution() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1 - rank / 100, "current_price": 50}
        for rank in range(1, 11)
    ]

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)

    assert diagnostics.redistributed_cash > 0
    assert any(item.final_quantity > item.initial_quantity for item in allocations)

