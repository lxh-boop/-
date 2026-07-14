from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_lot_infeasible_candidate_elimination() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1 - rank / 100, "current_price": 10}
        for rank in range(1, 10)
    ]
    candidates.append({"stock_code": "000010", "rank": 10, "final_action": "keep", "final_score": 0.1, "current_price": 1000})

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)
    removed = [item for item in allocations if item.removed_due_to_lot_constraint]

    assert removed
    assert removed[0].stock_code == "000010"
    assert diagnostics.removed_candidate_count == 1

