from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_position_ratio_uses_total_assets() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 50000, "position_market_value": 999, "total_assets": 999, "updated_at": "2026-07-17"},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 10, "market_value": 10000, "position_ratio": 0.99, "updated_at": "2026-07-17"}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["total_assets"] == 60000
    assert snapshot["positions"][0]["position_ratio"] == 1 / 6
