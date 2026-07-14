from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_recursive_round_logs_complete() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 10)
    ]
    candidates.append({"stock_code": "000010", "rank": 10, "final_action": "keep", "target_weight": 0.08, "current_price": 1000})

    _, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    round_log = diagnostics.lot_execution_rounds[0]

    required = {
        "round_no",
        "candidate_codes_before",
        "target_weights_before",
        "target_amounts_before",
        "target_quantities_before",
        "unaffordable_codes",
        "removed_stock_code",
        "removed_original_rank",
        "removed_target_weight",
        "removed_reason",
        "released_weight",
        "redistributed_weights",
        "candidate_codes_after",
        "target_weights_after",
        "target_amounts_after",
        "target_quantities_after",
        "remaining_unallocated_weight",
    }
    assert required <= set(round_log)
