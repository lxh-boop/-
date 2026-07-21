from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_portfolio_snapshot_consistent() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 88000, "position_market_value": 12000, "total_assets": 100000, "updated_at": "2026-07-17 09:00:00"},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12, "market_value": 12000, "updated_at": "2026-07-17 09:00:00"}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["consistency_status"] == "consistent"
    assert snapshot["position_market_value"] == 12000
    assert snapshot["total_assets"] == 100000
    assert snapshot["cash_ratio"] == 0.88
    assert snapshot["positions"][0]["position_ratio"] == 0.12
