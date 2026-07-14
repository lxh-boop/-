from __future__ import annotations

import pytest

from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.paper_trading_engine import execute_paper_rebalance
from portfolio.schemas import RebalanceDecision, RebalancePlan


def _plan(decisions: list[RebalanceDecision]) -> RebalancePlan:
    return RebalancePlan(
        user_id="user_001",
        trade_date="2026-06-11",
        decisions=decisions,
        total_target_weight=sum(item.target_weight for item in decisions),
    )


def test_paper_buy_reduces_cash_and_increases_position() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    decision = RebalanceDecision(
        stock_code="000001",
        stock_name="平安银行",
        action="buy",
        target_weight=0.10,
        reason="paper buy",
        current_price=10,
    )

    result = execute_paper_rebalance(account, [], _plan([decision]))

    assert result["is_paper_trading"] is True
    assert result["account"].cash == 89997
    assert result["positions"][0].quantity == 1000
    assert result["orders"][0].action == "buy"
    assert result["orders"][0].total_fee == pytest.approx(3)
    assert result["orders"][0].is_paper_trading is True


def test_paper_reduce_increases_cash_and_reduces_position() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    account = account.__class__(
        account_id=account.account_id,
        user_id=account.user_id,
        initial_cash=100000,
        cash=50000,
        total_assets=100000,
    )
    position = create_position(
        "user_001",
        "000001",
        quantity=5000,
        cost_price=10,
        current_price=10,
        total_assets=100000,
        industry="银行",
    )
    decision = RebalanceDecision(
        stock_code="000001",
        stock_name="平安银行",
        action="reduce",
        target_weight=0.20,
        reason="paper reduce",
        industry="银行",
        current_price=10,
    )

    result = execute_paper_rebalance(account, [position], _plan([decision]))

    assert result["account"].cash == 79976
    assert result["positions"][0].quantity == 2000
    assert result["orders"][0].action == "sell"
    assert result["orders"][0].paper_action == "paper_reduce"


def test_watchlist_decision_does_not_buy() -> None:
    account = create_default_account("user_001", initial_cash=100000)
    decision = RebalanceDecision(
        stock_code="000001",
        stock_name="平安银行",
        action="hold",
        target_weight=0.0,
        reason="paper watch",
        current_price=10,
    )

    result = execute_paper_rebalance(account, [], _plan([decision]))

    assert result["account"].cash == 100000
    assert result["positions"] == []
    assert result["orders"] == []
