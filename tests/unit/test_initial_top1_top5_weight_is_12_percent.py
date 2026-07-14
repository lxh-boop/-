from __future__ import annotations

from portfolio.hierarchical_top10_allocator import base_allocation_weight


def test_initial_top1_top5_weight_is_12_percent() -> None:
    assert base_allocation_weight(1) == 0.12
    assert base_allocation_weight(5) == 0.12
