from portfolio.portfolio_snapshot import build_portfolio_snapshot


def test_asset_fixture_122000_is_separate_or_removed() -> None:
    snapshot = build_portfolio_snapshot(
        {"user_id": "u1", "account_id": "paper_u1", "cash": 100000},
        [
            {"user_id": "u1", "stock_code": "000001", "quantity": 1000, "current_price": 12},
            {"user_id": "u1", "stock_code": "600519", "quantity": 1000, "current_price": 10},
        ],
        user_id="u1",
        account_id="paper_u1",
    )

    assert snapshot["total_assets"] == 122000
    assert len(snapshot["calculation_trace"]["position_components"]) == 2

