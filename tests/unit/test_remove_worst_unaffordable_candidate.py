from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_remove_worst_unaffordable_candidate() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 0.9, "current_price": 10}
        for rank in range(1, 9)
    ]
    candidates.extend(
        [
            {"stock_code": "000009", "rank": 9, "final_action": "keep", "final_score": 0.1, "current_price": 1000},
            {"stock_code": "000010", "rank": 10, "final_action": "keep", "final_score": 0.9, "current_price": 1000},
        ]
    )

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)
    first_removed = sorted([item for item in allocations if item.removed_due_to_lot_constraint], key=lambda item: item.removed_round)[0]

    assert first_removed.stock_code == "000010"
    assert diagnostics.removed_candidates[0]["stock_code"] == "000010"

