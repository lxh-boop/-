from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_planned_executable_actual_metrics_separated() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 11)
    ]

    _, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)

    payload = diagnostics.to_dict()
    assert "normalized_target_weight_sum" in payload
    assert "executable_candidate_count" in payload
    assert "actual_invested_cash" in payload
    assert "unavoidable_residual_cash" in payload
