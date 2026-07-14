import pytest

from portfolio.hierarchical_top10_allocator import allocate_hierarchical_top10, effective_news_multiplier


def test_top10_news_adjusted_normalization() -> None:
    candidates = [
        {
            "stock_code": f"{rank:06d}",
            "rank": rank,
            "final_action": "keep",
            "final_score": 1 - rank / 100,
            "current_price": 10,
            "raw_news_multiplier": 0.5 if rank == 1 else 1.0,
            "ai_reliability_weight": 1.0,
        }
        for rank in range(1, 11)
    ]

    allocations, diagnostics = allocate_hierarchical_top10(candidates, total_assets=100000)
    by_code = {item.stock_code: item for item in allocations}

    assert effective_news_multiplier(0.5, 0.0) == pytest.approx(1.0)
    assert diagnostics.normalized_target_weight_sum == pytest.approx(0.80)
    assert by_code["000001"].effective_news_multiplier == pytest.approx(0.5)
    assert by_code["000001"].target_weight < by_code["000002"].target_weight

