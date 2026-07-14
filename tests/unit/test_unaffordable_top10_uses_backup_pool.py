from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_unaffordable_top10_does_not_use_backup_pool() -> None:
    candidates = [{"stock_code": "000001", "rank": 1, "final_action": "keep", "target_weight": 0.08, "current_price": 1000000}]
    candidates.extend(
        {"stock_code": f"{i:06d}", "rank": i, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for i in range(11, 16)
    )
    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    assert diagnostics.replacement_candidates == []
    assert diagnostics.backup_candidate_count == 0
    assert all(not item.is_backup_candidate for item in allocations)
