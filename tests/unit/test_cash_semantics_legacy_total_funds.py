from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_cash_semantics_legacy_total_funds() -> None:
    snapshot = build_portfolio_snapshot(
        {
            "user_id": "u1",
            "account_id": "paper_u1",
            "cash": 100000,
            "total_funds": 100000,
            "total_assets": 100000,
        },
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["total_assets"] == 112000
    assert "recomputed_stale_total_assets" in snapshot["warnings"]

