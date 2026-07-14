from portfolio.account_reconciliation import RECONCILIATION_FAILED, reconcile_account_day


def test_invalid_position_transition_rejected() -> None:
    result = reconcile_account_day(
        "2026-06-03",
        account={"cash": 100000, "total_assets": 100000},
        positions=[],
        orders=[{"stock_code": "000001", "paper_action": "paper_sell", "quantity": 100, "executed_price": 10}],
        previous_row={"cash": 90000, "position_count": 1, "recalculated_total_asset": 100000},
        previous_positions=[{"stock_code": "000001", "quantity": 1000, "current_price": 10}],
    )

    assert result.reconciliation_status == RECONCILIATION_FAILED
    assert "000001" in result.invalid_reason

