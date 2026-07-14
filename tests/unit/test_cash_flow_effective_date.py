from portfolio.cash_flow import apply_cash_flows_to_account, make_cash_flow
from portfolio.paper_account import create_default_account


def test_future_effective_date_is_not_applied(tmp_path) -> None:
    account = create_default_account("u1", initial_cash=100000)
    flow = make_cash_flow("u1", "deposit", 50000, "2026-05-04")

    updated, applied, warnings = apply_cash_flows_to_account(
        account,
        [flow],
        "2026-05-01",
        output_dir=tmp_path,
        use_database=False,
        persist_status=False,
    )

    assert updated.cash == 100000
    assert applied == []
    assert warnings == []
