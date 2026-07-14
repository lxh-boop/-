from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_final_single_position_cap_30_percent() -> None:
    candidates = [
        {"stock_code": "000001", "rank": 1, "final_action": "keep", "target_weight": 1.0, "current_price": 10},
        {"stock_code": "000002", "rank": 2, "final_action": "keep", "target_weight": 0.01, "current_price": 10},
    ]
    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    assert max(item.target_weight for item in allocations) <= 0.30
    assert diagnostics.maximum_final_position_weight == 0.30
