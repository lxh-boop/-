import pytest

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10


def test_reallocate_after_each_single_removal() -> None:
    candidates = [
        {"stock_code": f"{rank:06d}", "rank": rank, "final_action": "keep", "target_weight": 0.08, "current_price": 10}
        for rank in range(1, 10)
    ]
    candidates.append({"stock_code": "000010", "rank": 10, "final_action": "keep", "target_weight": 0.08, "current_price": 1000})

    _, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000, cash=100000)
    first_round = diagnostics.lot_execution_rounds[0]

    assert first_round["candidate_codes_after"] == [f"{rank:06d}" for rank in range(1, 10)]
    assert sum(first_round["target_weights_after"].values()) == pytest.approx(0.80)
