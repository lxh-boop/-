from portfolio.portfolio_snapshot import CASH_SEMANTICS_UNINVESTED_CASH, build_portfolio_snapshot


def test_cash_semantics_uninvested_cash() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 88000},
        [{"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12}],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["cash_semantics"] == CASH_SEMANTICS_UNINVESTED_CASH
    assert snapshot["total_assets"] == 100000

