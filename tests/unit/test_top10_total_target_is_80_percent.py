import pytest

from portfolio.hierarchical_top10_allocator import TOP10_TARGET_RATIO, allocate_hierarchical_top10


def test_top10_total_target_is_80_percent() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1, "current_price": 10}
        for rank in range(1, 11)
    ]

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)

    assert sum(item.target_weight for item in allocations if not item.removed_due_to_lot_constraint) == pytest.approx(TOP10_TARGET_RATIO)
    assert diagnostics.normalized_target_weight_sum == pytest.approx(TOP10_TARGET_RATIO)

