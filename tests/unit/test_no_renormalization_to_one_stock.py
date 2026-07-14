from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_no_renormalization_to_one_stock() -> None:
    allocations, _ = allocate_hierarchical_top10(
        [{"stock_code": "000001", "rank": 1, "final_action": "keep", "target_weight": 0.08, "current_price": 8}],
        total_assets=100000,
        cash=100000,
    )
    assert max(item.target_weight for item in allocations) <= 0.30
