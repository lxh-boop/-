from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_total_assets_no_double_count() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["total_assets"] == 100000 + 12000
    assert snapshot["total_assets"] != 124000

