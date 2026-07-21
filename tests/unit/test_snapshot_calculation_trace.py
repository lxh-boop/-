from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_snapshot_calculation_trace() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 500},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 100, "current_price": 10}],
        user_id="u1",
        account_id="paper_u1",
    )

    trace = snapshot["calculation_trace"]
    assert trace["total_assets_formula"] == "uninvested_cash + position_market_value_sum"
    assert trace["cash_used"] == 500
    assert trace["position_components"] == [{"stock_code": "000001", "quantity": 100.0, "current_price": 10.0, "market_value": 1000.0}]

