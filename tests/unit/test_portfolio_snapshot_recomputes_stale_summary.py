from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_portfolio_snapshot_recomputes_stale_summary() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000, "position_market_value": 0, "total_assets": 100000, "updated_at": "2026-07-17 09:00:00"},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12, "market_value": 12000, "updated_at": "2026-07-17 09:00:00"}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["consistency_status"] == "recomputed_stale_summary"
    assert snapshot["position_market_value"] == 12000
    assert snapshot["total_assets"] == 112000
    assert snapshot["cash_ratio"] == 100000 / 112000
    assert "recomputed_stale_position_market_value" in snapshot["warnings"]
