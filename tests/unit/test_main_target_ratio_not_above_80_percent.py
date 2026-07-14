from portfolio.hierarchical_top10_allocator import TOP10_TARGET_RATIO, allocate_hierarchical_top10


def test_main_target_ratio_not_above_80_percent() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.50, "current_price": 10}
        for rank in range(1, 11)
    ]

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    assert sum(item.target_weight for item in allocations if not item.removed_due_to_lot_constraint) <= TOP10_TARGET_RATIO + 1e-9
    assert diagnostics.normalized_target_weight_sum <= TOP10_TARGET_RATIO + 1e-9
