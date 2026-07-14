from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_single_position_never_gets_80_percent() -> None:
    allocations, diagnostics = allocate_hierarchical_top10(
        [{"stock_code": "000001", "rank": 1, "final_action": "keep", "target_weight": 0.08, "current_price": 10}],
        total_assets=100000,
        cash=100000,
    )
    active = [item for item in allocations if item.final_quantity > 0]
    assert len(active) == 1
    assert active[0].target_weight <= 0.30
    assert diagnostics.unallocated_ratio > 0
