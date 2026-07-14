from portfolio.account_reconciliation import RECONCILIATION_FAILED, reconcile_account_day


def test_no_asset_change_without_business_event() -> None:
    previous = {"cash": 100000, "position_count": 0, "recalculated_total_asset": 100000}
    result = reconcile_account_day(
        trade_date="2026-04-02",
        account={"cash": 99900, "total_assets": 99900},
        positions=[],
        orders=[],
        cash_flows=[],
        previous_row=previous,
    )

    assert result.reconciliation_status == RECONCILIATION_FAILED
    assert result.no_business_event_violation is True

