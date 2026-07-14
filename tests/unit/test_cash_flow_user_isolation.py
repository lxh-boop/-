from portfolio.cash_flow import add_cash_flow, list_cash_flows


def test_cash_flows_are_isolated_by_user_id(tmp_path) -> None:
    add_cash_flow("u1", "deposit", 1000, "2026-05-04", output_dir=tmp_path, use_database=False)
    add_cash_flow("u2", "deposit", 2000, "2026-05-04", output_dir=tmp_path, use_database=False)

    assert [flow.amount for flow in list_cash_flows("u1", output_dir=tmp_path, use_database=False)] == [1000]
    assert [flow.amount for flow in list_cash_flows("u2", output_dir=tmp_path, use_database=False)] == [2000]
