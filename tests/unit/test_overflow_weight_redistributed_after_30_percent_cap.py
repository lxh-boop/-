from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_overflow_weight_redistributed_after_30_percent_cap() -> None:
    candidates = [
        {"stock_code": "000001", "rank": 1, "final_action": "", "target_weight": 1.0, "current_price": 10},
        {"stock_code": "000002", "rank": 2, "final_action": "", "target_weight": 0.2, "current_price": 10},
        {"stock_code": "000003", "rank": 3, "final_action": "", "target_weight": 0.2, "current_price": 10},
    ]
    allocations, _ = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    assert any(item.capped_overflow_weight > 0 for item in allocations)
    assert any(item.redistributed_weight_received > 0 for item in allocations)
