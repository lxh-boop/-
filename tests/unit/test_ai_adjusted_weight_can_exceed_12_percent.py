from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_ai_adjusted_weight_can_exceed_12_percent() -> None:
    candidates = [
        {"stock_code": f"{i:06d}", "rank": i, "final_action": "keep", "target_weight": 0.20 if i == 1 else 0.05, "current_price": 10}
        for i in range(1, 6)
    ]
    allocations, _ = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    first = next(item for item in allocations if item.stock_code == "000001")
    assert first.target_weight > 0.12
    assert first.target_weight <= 0.30
