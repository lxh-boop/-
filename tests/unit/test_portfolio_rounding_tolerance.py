from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_portfolio_rounding_tolerance() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000, "position_market_value": 12000.005, "total_assets": 112000.005, "updated_at": "2026-07-17"},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12, "market_value": 12000, "updated_at": "2026-07-17"}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["consistency_status"] == "consistent"
    assert snapshot["warnings"] == []
