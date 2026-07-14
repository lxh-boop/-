from portfolio.cash_flow import apply_cash_flows_to_account, make_cash_flow
from portfolio.paper_account import create_default_account


def test_historical_cash_flow_applies_from_effective_date_only(tmp_path) -> None:
    account = create_default_account("u1", initial_cash=100000)
    flow = make_cash_flow("u1", "deposit", 50000, "2026-05-04")

    before, _, _ = apply_cash_flows_to_account(account, [flow], "2026-05-01", output_dir=tmp_path, use_database=False, persist_status=False)
    after, applied, _ = apply_cash_flows_to_account(before, [flow], "2026-05-04", output_dir=tmp_path, use_database=False, persist_status=False)

    assert before.cash == 100000
    assert after.cash == 150000
    assert applied[0].effective_date == "2026-05-04"
