from __future__ import annotations

import pytest

from portfolio.paper_order import create_paper_order


def test_create_paper_order_marks_paper_trading() -> None:
    order = create_paper_order(
        user_id="user_001",
        trade_date="2026-06-11",
        stock_code="1",
        action="buy",
        target_weight=0.08,
        executed_price=10,
        quantity=800,
        reason="paper test",
    )

    assert order.stock_code == "000001"
    assert order.is_paper_trading is True
    assert order.to_dict()["is_paper_trading"] == 1
    assert order.gross_amount == 8000
    assert order.total_fee > 0


def test_invalid_paper_order_action_raises() -> None:
    with pytest.raises(ValueError):
        create_paper_order(
            user_id="user_001",
            trade_date="2026-06-11",
            stock_code="000001",
            action="real_trade",
            target_weight=0,
            executed_price=0,
            quantity=0,
            reason="invalid",
        )
