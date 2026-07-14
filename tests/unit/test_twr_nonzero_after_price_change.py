from portfolio.paper_account import create_default_account
from portfolio.paper_position import create_position
from portfolio.performance_metrics import build_nav_record


def test_twr_nonzero_after_price_change() -> None:
    account = create_default_account("u1", 100000)
    account = account.__class__(**{**account.to_dict(), "cash": 90000, "total_assets": 102000})
    position = create_position("u1", "000001", quantity=1000, cost_price=10, current_price=12, total_assets=102000)

    record = build_nav_record(account, "2026-04-02", [position], previous_total_assets=100000)

    assert record["time_weighted_return"] > 0
    assert record["daily_return"] > 0

