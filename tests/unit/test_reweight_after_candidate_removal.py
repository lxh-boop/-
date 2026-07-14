import pytest

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_reweight_after_candidate_removal() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "final_score": 1, "current_price": 10}
        for rank in range(1, 10)
    ]
    candidates.append({"stock_code": "000010", "rank": 10, "final_action": "keep", "final_score": 1, "current_price": 1000})

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)
    active = [item for item in allocations if not item.removed_due_to_lot_constraint]

    assert len(active) == 9
    assert sum(item.target_weight for item in active) == pytest.approx(0.80)
    assert diagnostics.normalized_target_weight_sum == pytest.approx(0.80)

