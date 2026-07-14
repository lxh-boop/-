from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_all_remaining_candidates_buyable() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1, "current_price": 10 if rank < 10 else 1000}
        for rank in range(1, 11)
    ]

    allocations, _ = allocate_hierarchical_top10(candidates, total_assets=100000)
    active = [item for item in allocations if not item.removed_due_to_lot_constraint]

    assert active
    assert all(item.final_quantity >= 100 for item in active)

