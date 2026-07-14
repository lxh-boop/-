from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_existing_position_not_removed_for_small_increment() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 10)
    ]
    candidates.append(
        {
            "stock_code": "000010",
            "rank": 10,
            "final_action": "keep",
            "target_weight": 0.01,
            "current_price": 1000,
            "current_quantity": 100,
            "current_weight": 0.05,
        }
    )

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    by_code = {item.stock_code: item for item in allocations}

    assert not by_code["000010"].removed_due_to_lot_constraint
    assert "000010" not in [item["stock_code"] for item in diagnostics.removed_candidates]
