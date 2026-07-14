import pytest

from portfolio.hierarchical_top10_allocator import base_allocation_score, normalize_base_scores


def _candidates():
    return [{"stock_code": f"{rank:06d}", "rank": rank} for rank in range(1, 11)]


def test_top10_base_score_normalization() -> None:
    weights = normalize_base_scores(_candidates())

    assert base_allocation_score(1) == 12
    assert base_allocation_score(5) == 12
    assert base_allocation_score(6) == 5
    assert base_allocation_score(10) == 5
    assert weights["000001"] == pytest.approx(0.80 * 12 / 85)
    assert weights["000006"] == pytest.approx(0.80 * 5 / 85)
    assert sum(weights.values()) == pytest.approx(0.80)

