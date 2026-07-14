from portfolio.account_reconciliation import RECONCILIATION_FAILED, is_valid_curve_point


def test_invalid_curve_point_excluded() -> None:
    row = {"trade_date": "2026-04-02", "is_trading_day": True, "reconciliation_status": RECONCILIATION_FAILED}

    assert is_valid_curve_point(row) is False

