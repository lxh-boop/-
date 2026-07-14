from app.pages.ai_paper_trading import build_capital_summary_rows


def test_total_asset_primary_metric() -> None:
    rows = build_capital_summary_rows(
        {"total_assets": 152162.19, "net_contribution": 150000, "absolute_profit": 2162.19},
        {},
        {},
        "cht",
        {},
    )

    assert rows[0][0]["label"] == "当前总资产"
    assert rows[0][0]["value"] == "152,162.19"
