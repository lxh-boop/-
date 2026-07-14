import pandas as pd

from app.pages.ai_paper_trading import build_asset_curve_table


def test_cash_flow_visible_in_asset_chart() -> None:
    table = build_asset_curve_table(
        pd.DataFrame(
            [
                {
                    "trade_date": "2026-04-01",
                    "total_assets": 150000,
                    "net_contribution": 150000,
                    "position_market_value": 0,
                    "cash": 150000,
                    "daily_deposit": 50000,
                    "daily_withdrawal": 0,
                }
            ]
        )
    )

    assert "当日入金" in table.columns
    assert table.iloc[0]["净投入资金"] == 150000
    assert table.iloc[0]["当日入金"] == 50000

