from portfolio.cash_flow import apply_cash_flows_to_account, make_cash_flow
from portfolio.paper_account import create_default_account, update_account_metrics


def test_twr_does_not_treat_deposit_as_profit(tmp_path) -> None:
    account = create_default_account("u1", initial_cash=100000)
    flow = make_cash_flow("u1", "deposit", 50000, "2026-05-04")

    after_flow, _, _ = apply_cash_flows_to_account(
        account,
        [flow],
        "2026-05-04",
        output_dir=tmp_path,
        use_database=False,
        persist_status=False,
    )
    no_profit = update_account_metrics(after_flow, positions_value=0, previous_total_assets=after_flow.total_assets)
    profit = update_account_metrics(no_profit, positions_value=15000, previous_total_assets=no_profit.total_assets)

    assert no_profit.absolute_profit == 0
    assert no_profit.time_weighted_return == 0
    assert round(profit.time_weighted_return, 4) == 0.10
