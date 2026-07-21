from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_empty_positions_cash_only_account() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000, "position_market_value": 0, "total_assets": 100000},
        [],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["position_market_value"] == 0
    assert snapshot["total_assets"] == 100000
    assert snapshot["cash_ratio"] == 1
    assert snapshot["positions"] == []
