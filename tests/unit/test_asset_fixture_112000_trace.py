from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_asset_fixture_112000_trace() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["total_assets"] == 112000
    assert snapshot["calculation_trace"]["position_market_value_sum"] == 12000
    assert snapshot["calculation_trace"]["total_assets"] == 112000

