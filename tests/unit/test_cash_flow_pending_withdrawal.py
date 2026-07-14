from portfolio.cash_flow import apply_cash_flows_to_account, make_cash_flow
from portfolio.schemas import PaperAccount


def test_withdrawal_over_cash_stays_pending_when_assets_are_enough(tmp_path) -> None:
    account = PaperAccount(account_id="paper_u1", user_id="u1", initial_cash=100000, cash=10000, total_assets=120000)
    flow = make_cash_flow("u1", "withdrawal", 50000, "2026-05-04")

    updated, applied, warnings = apply_cash_flows_to_account(
        account,
        [flow],
        "2026-05-04",
        output_dir=tmp_path,
        use_database=False,
        persist_status=False,
    )

    assert updated.cash == 10000
    assert applied == []
    assert "pending" in warnings[0]
