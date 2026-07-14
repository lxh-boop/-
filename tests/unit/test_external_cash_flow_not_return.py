from portfolio.performance_metrics import build_nav_record
from portfolio.paper_account import create_default_account


def test_external_cash_flow_does_not_create_composite_nav_return() -> None:
    account = create_default_account("u1", initial_cash=100000)
    account = account.__class__(
        **{
            **account.to_dict(),
            "cash": 150000,
            "total_assets": 150000,
            "cumulative_deposit": 50000,
            "net_contribution": 150000,
        }
    )

    record = build_nav_record(
        account,
        "2026-05-04",
        [],
        previous_total_assets=100000,
        previous_twr=0.0,
        daily_deposit=50000,
    )

    assert record["daily_return"] == 0
    assert record["composite_nav"] == 1.0
