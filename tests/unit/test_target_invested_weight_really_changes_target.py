import pytest

from portfolio.rebalance_rules import build_rebalance_plan
from strategy_runtime_test_utils import runtime_account, runtime_candidates


def test_target_invested_weight_really_changes_target() -> None:
    low = build_rebalance_plan(
        "u1",
        "2026-07-16",
        runtime_candidates(),
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        target_invested_weight=0.55,
    )
    default = build_rebalance_plan(
        "u1",
        "2026-07-16",
        runtime_candidates(),
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        target_invested_weight=0.80,
    )

    assert low.execution_diagnostics["top10_target_weight_sum"] == (
        pytest.approx(0.55)
    )
    assert default.execution_diagnostics["top10_target_weight_sum"] == (
        pytest.approx(0.80)
    )
