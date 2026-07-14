from portfolio.performance_metrics import build_nav_record
from portfolio.paper_account import create_default_account


def test_external_flow_not_counted_as_profit() -> None:
    account = create_default_account("u1", initial_cash=100000).__class__(
        account_id="paper_u1",
        user_id="u1",
        initial_cash=100000,
        cash=150000,
        total_assets=150000,
        cumulative_deposit=50000,
        net_contribution=150000,
    )

    record = build_nav_record(account, "2026-04-02", [], previous_total_assets=100000, daily_deposit=50000)

    assert record["daily_profit"] == 0
    assert record["daily_return"] == 0

