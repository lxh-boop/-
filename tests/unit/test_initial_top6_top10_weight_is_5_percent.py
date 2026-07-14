from __future__ import annotations

from portfolio.hierarchical_top10_allocator import base_allocation_weight


def test_initial_top6_top10_weight_is_5_percent() -> None:
    assert base_allocation_weight(6) == 0.05
    assert base_allocation_weight(10) == 0.05
