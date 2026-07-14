from portfolio.account_reconciliation import RECONCILIATION_PASSED, reconcile_account_day


def test_account_asset_equals_cash_plus_positions() -> None:
    result = reconcile_account_day(
        "2026-05-11",
        account={"cash": 90000, "total_assets": 101000},
        positions=[{"stock_code": "000001", "quantity": 1000, "current_price": 11}],
    )

    assert result.reconciliation_status == RECONCILIATION_PASSED
    assert result.recalculated_total_asset == 101000

