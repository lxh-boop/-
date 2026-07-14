from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_previously_unaffordable_can_become_affordable_after_reallocation() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 9)
    ]
    candidates.append({"stock_code": "000009", "rank": 9, "final_action": "keep", "target_weight": 0.08, "current_price": 88})
    candidates.append({"stock_code": "000010", "rank": 10, "final_action": "keep", "target_weight": 0.08, "current_price": 1000})

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    by_code = {item.stock_code: item for item in allocations}

    assert "000009" in diagnostics.lot_execution_rounds[0]["unaffordable_codes"]
    assert by_code["000009"].final_quantity >= 100
    assert by_code["000010"].removed_due_to_lot_constraint
