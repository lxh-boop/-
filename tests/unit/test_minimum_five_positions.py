from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_minimum_five_positions_when_candidates_are_available() -> None:
    candidates = [
        {"stock_code": f"{i:06d}", "rank": i, "final_action": "", "target_weight": 0.08, "current_price": 10}
        for i in range(1, 6)
    ]
    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    assert len([item for item in allocations if item.final_quantity > 0]) >= 5
    assert diagnostics.insufficient_diversified_candidates is False
