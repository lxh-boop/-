from __future__ import annotations

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.portfolio_risk import calculate_portfolio_risk
from portfolio.user_profile import build_user_constraints, default_user_profile


def test_portfolio_risk_detects_concentration_and_drawdown() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    account = account.__class__(
        account_id=account.account_id,
        user_id=account.user_id,
        initial_cash=100000,
        cash=50000,
        total_assets=100000,
        max_drawdown=-0.20,
    )
    positions = [
        {
            "user_id": "user_001",
            "stock_code": "000001",
            "quantity": 3000,
            "cost_price": 10,
            "current_price": 10,
            "industry": "银行",
            "risk_level": "high",
        },
        {
            "user_id": "user_001",
            "stock_code": "000002",
            "quantity": 2000,
            "cost_price": 10,
            "current_price": 10,
            "industry": "银行",
        },
    ]
    constraints = build_user_constraints(default_user_profile("user_001", "稳健型"))

    report = calculate_portfolio_risk("user_001", account, positions, constraints)

    assert report.max_single_position == 0.30
    assert report.industry_concentration["银行"] == 0.50
    assert report.high_risk_position_ratio == 0.30
    assert report.user_risk_match is False
    assert report.risk_level in {"high", "extreme"}
    assert report.risk_warnings


def test_portfolio_risk_low_when_no_positions() -> None:
    account = create_default_account("user_001", initial_cash=100000)

    report = calculate_portfolio_risk("user_001", account, [], None)

    assert report.risk_level == "low"
    assert report.cash_ratio == 1.0
    assert report.holding_count == 0
    assert report.risk_warnings == []
