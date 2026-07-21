from strategy_baseline_helpers import (
    build_strategy_golden_result,
    normalized_orders,
    normalized_target,
)
import pytest


def test_default_strategy_golden_unchanged() -> None:
    fixture, plan, result = build_strategy_golden_result()
    expected = fixture["expected"]

    assert normalized_target(plan) == expected["target_portfolio"]
    assert normalized_orders(result) == expected["orders"]
    assert result["account"].cash == pytest.approx(
        expected["account"]["cash"]
    )
    assert {
        item.stock_code: float(item.quantity)
        for item in result["positions"]
    } == expected["position_quantities"]
