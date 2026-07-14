from portfolio.account_reconciliation import RECONCILIATION_FAILED, reconcile_account_day


def test_position_zero_requires_sell_order() -> None:
    result = reconcile_account_day(
        "2026-05-11",
        account={"cash": 100000, "total_assets": 100000},
        positions=[],
        orders=[],
        previous_row={"cash": 90000, "position_count": 1, "recalculated_total_asset": 100000},
        previous_positions=[{"stock_code": "000001", "quantity": 1000, "current_price": 10}],
    )

    assert result.reconciliation_status == RECONCILIATION_FAILED
    assert "previous_position_nonzero" in result.invalid_reason

