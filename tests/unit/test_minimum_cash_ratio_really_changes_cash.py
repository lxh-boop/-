import pytest

from portfolio.rebalance_rules import build_rebalance_plan
from strategy_runtime_test_utils import runtime_account, runtime_candidates


def test_minimum_cash_ratio_really_changes_cash() -> None:
    plan = build_rebalance_plan(
        "u1",
        "2026-07-16",
        runtime_candidates(),
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        target_invested_weight=0.95,
        minimum_cash_ratio=0.30,
    )

    assert plan.execution_diagnostics["top10_target_ratio"] == (
        pytest.approx(0.70)
    )
    assert plan.execution_diagnostics["top10_target_weight_sum"] == (
        pytest.approx(0.70)
    )
