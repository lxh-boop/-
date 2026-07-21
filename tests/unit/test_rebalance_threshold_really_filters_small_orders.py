from portfolio.rebalance_rules import build_rebalance_plan
from strategy_runtime_test_utils import runtime_account


def test_rebalance_threshold_really_filters_small_orders() -> None:
    plan = build_rebalance_plan(
        "u1",
        "2026-07-16",
        [
            {
                "stock_code": "000001",
                "rank": 1,
                "original_rank": 1,
                "original_score": 1.0,
                "current_price": 1.0,
                "risk_level": "low",
            }
        ],
        account=runtime_account(),
        strategy_mode="hierarchical_top10",
        target_invested_weight=0.005,
        minimum_cash_ratio=0.05,
        min_rebalance_weight_delta=0.01,
    )

    assert plan.decisions[0].target_weight == 0.005
    assert plan.decisions[0].action == "hold"
