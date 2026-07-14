from __future__ import annotations

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_insufficient_candidates_keep_residual_cash() -> None:
    allocations, diagnostics = allocate_hierarchical_top10(
        [{"stock_code": "000001", "rank": 1, "final_action": "keep", "target_weight": 0.08, "current_price": 10}],
        total_assets=100000,
        cash=100000,
    )
    assert sum(item.final_weight for item in allocations) < 0.80
    assert diagnostics.unallocated_ratio > 0
