from portfolio.paper_account import create_default_account
from portfolio.performance_metrics import build_nav_record


def test_nav_record_uses_composite_nav_alias() -> None:
    account = create_default_account("u1", 100000)
    record = build_nav_record(account, "2026-04-01", [], previous_total_assets=100000)

    assert "composite_nav" in record
    assert record["composite_nav"] == record["nav"]
    assert record["composite_nav"] == 1.0
