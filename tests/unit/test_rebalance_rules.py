from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.rebalance_rules import build_rebalance_plan
from portfolio.user_profile import build_user_constraints, default_user_profile


def test_conservative_user_reduces_high_risk_stock_position() -> None:
    constraints = build_user_constraints(default_user_profile("user_001", "保守型"))
    plan = build_rebalance_plan(
        user_id="user_001",
        trade_date="2026-06-11",
        candidates=[
            {
                "stock_code": "000001",
                "stock_name": "平安银行",
                "final_score": 0.95,
                "risk_level": "high",
                "industry": "银行",
                "action": "buy",
                "current_price": 10,
            }
        ],
        user_constraints=constraints,
    )

    assert plan.decisions[0].action == "buy"
    assert 0 < plan.decisions[0].target_weight <= constraints["max_single_position"] * 0.5
    assert plan.decisions[0].is_paper_trading is True


def test_industry_concentration_blocks_same_industry_buy() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    current = create_position(
        "user_001",
        "000001",
        quantity=3000,
        cost_price=10,
        current_price=10,
        total_assets=100000,
        industry="银行",
    )
    constraints = build_user_constraints(default_user_profile("user_001", "稳健型"))
    plan = build_rebalance_plan(
        user_id="user_001",
        trade_date="2026-06-11",
        candidates=[
            {
                "stock_code": "000002",
                "stock_name": "万科A",
                "final_score": 0.90,
                "risk_level": "medium",
                "industry": "银行",
                "action": "buy",
                "current_price": 10,
            }
        ],
        user_constraints=constraints,
        current_positions=[current],
        account=account,
    )

    assert plan.decisions[0].action == "hold"
    assert "行业" in plan.decisions[0].risk_warning


def test_reduce_or_watchlist_candidates_do_not_generate_buy_actions() -> None:
    constraints = build_user_constraints(default_user_profile("user_001", "激进型"))
    plan = build_rebalance_plan(
        user_id="user_001",
        trade_date="2026-06-11",
        candidates=[
            {"stock_code": "000001", "final_score": 0.9, "risk_level": "low", "industry": "银行", "action": "reduce"},
            {"stock_code": "000002", "final_score": 0.8, "risk_level": "low", "industry": "地产", "action": "hold"},
        ],
        user_constraints=constraints,
    )

    assert {decision.action for decision in plan.decisions}.isdisjoint({"buy"})
