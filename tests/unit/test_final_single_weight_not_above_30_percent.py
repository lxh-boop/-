from portfolio.hierarchical_top10_allocator import MAXIMUM_FINAL_POSITION_WEIGHT, allocate_hierarchical_top10


def test_final_single_weight_not_above_30_percent() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.01, "current_price": 10}
        for rank in range(1, 11)
    ]
    candidates[0]["target_weight"] = 0.90

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    assert max(item.target_weight for item in allocations) <= MAXIMUM_FINAL_POSITION_WEIGHT + 1e-9
    assert diagnostics.over_30_position_count == 0
