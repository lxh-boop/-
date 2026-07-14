from __future__ import annotations

from portfolio.paper_position import create_position, position_from_dict


def test_create_position_calculates_value_ratio_and_pnl() -> None:
    position = create_position(
        user_id="user_001",
        stock_code="1",
        stock_name="平安银行",
        quantity=1000,
        cost_price=9,
        current_price=10,
        total_assets=100000,
        industry="银行",
    )

    assert position.stock_code == "000001"
    assert position.market_value == 10000
    assert position.position_ratio == 0.10
    assert position.unrealized_pnl == 1000


def test_position_database_record_is_compatible_with_portfolio_position_table() -> None:
    position = create_position("user_001", "000001", quantity=100, cost_price=10, current_price=11)
    record = position.to_database_record()

    assert record["asset_code"] == "000001"
    assert record["asset_type"] == "股票"
    assert record["profit_loss"] == 100


def test_position_from_database_like_dict() -> None:
    position = position_from_dict(
        {
            "user_id": "user_001",
            "asset_code": "000002",
            "asset_name": "万科A",
            "quantity": 100,
            "cost_price": 20,
            "current_price": 18,
            "industry": "地产",
        },
        total_assets=100000,
    )

    assert position.stock_code == "000002"
    assert position.unrealized_pnl == -200
