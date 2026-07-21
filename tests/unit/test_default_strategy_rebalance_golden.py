from __future__ import annotations

import pytest

from strategy_baseline_helpers import (
    build_strategy_golden_result,
    normalized_orders,
    normalized_target,
)


def test_default_strategy_rebalance_matches_phase0_golden() -> None:
    fixture, plan, result = build_strategy_golden_result()
    expected = fixture["expected"]

    assert normalized_target(plan) == expected["target_portfolio"]
    assert normalized_orders(result) == expected["orders"]
    account = result["account"]
    assert account.cash == pytest.approx(expected["account"]["cash"])
    assert account.total_assets == pytest.approx(
        expected["account"]["total_assets"]
    )
    assert account.daily_fee == pytest.approx(
        expected["account"]["daily_fee"]
    )
    assert account.cumulative_fee == pytest.approx(
        expected["account"]["cumulative_fee"]
    )
    assert {
        item.stock_code: float(item.quantity)
        for item in result["positions"]
    } == expected["position_quantities"]
    assert plan.execution_diagnostics["top10_target_weight_sum"] == (
        pytest.approx(0.8)
    )
