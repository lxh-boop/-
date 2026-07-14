from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_recursive_lot_feasibility_removes_one_stock_per_round() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 8)
    ]
    candidates.extend(
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 1000}
        for rank in range(8, 11)
    )

    _, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    assert diagnostics.lot_execution_rounds
    assert len(diagnostics.removed_candidates) == len(diagnostics.lot_execution_rounds)
    assert all(round_log["removed_stock_code"] for round_log in diagnostics.lot_execution_rounds)
