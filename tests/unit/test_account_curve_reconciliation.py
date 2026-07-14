from portfolio.account_reconciliation import RECONCILIATION_PASSED, reconcile_account_day


def test_account_curve_reconciliation() -> None:
    result = reconcile_account_day(
        trade_date="2026-04-01",
        account={"cash": 90000, "total_assets": 100000},
        positions=[{"stock_code": "000001", "quantity": 1000, "current_price": 10}],
    )

    assert result.reconciliation_status == RECONCILIATION_PASSED
    assert result.recalculated_total_asset == 100000
    assert result.asset_difference == 0

