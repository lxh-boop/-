from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_no_backup_candidates_enter_fixed_original_top10() -> None:
    candidates = [{"stock_code": "000010", "rank": 10, "final_action": "keep", "target_weight": 0.08, "current_price": 1000}]
    candidates.extend(
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(11, 16)
    )

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    assert diagnostics.backup_candidate_count == 0
    assert diagnostics.replacement_candidates == []
    assert all(item.final_rank <= 10 for item in allocations)
