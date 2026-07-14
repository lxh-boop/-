from portfolio.cash_flow import apply_cash_flows_to_account, make_cash_flow
from portfolio.paper_account import create_default_account


def test_withdrawal_reduces_cash_without_negative_balance(tmp_path) -> None:
    account = create_default_account("u1", initial_cash=100000)
    flow = make_cash_flow("u1", "withdrawal", 30000, "2026-05-04")

    updated, applied, warnings = apply_cash_flows_to_account(
        account,
        [flow],
        "2026-05-04",
        output_dir=tmp_path,
        use_database=False,
        persist_status=False,
    )

    assert warnings == []
    assert len(applied) == 1
    assert updated.cash == 70000
    assert updated.cumulative_withdrawal == 30000
    assert updated.net_contribution == 70000
