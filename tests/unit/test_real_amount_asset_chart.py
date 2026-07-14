import pandas as pd

from app.pages.ai_paper_trading import ASSET_CURVE_TITLE, build_asset_curve_chart_data


def test_real_amount_asset_chart() -> None:
    chart = build_asset_curve_chart_data(
        pd.DataFrame(
            [
                {
                    "trade_date": "2026-04-01",
                    "total_assets": 100000,
                    "net_contribution": 100000,
                    "position_market_value": 20000,
                    "cash": 80000,
                    "composite_nav": 1.0,
                }
            ]
        )
    )

    assert ASSET_CURVE_TITLE == "账户资产走势"
    assert "账户总资产" in chart.columns
    assert "净投入资金" in chart.columns
    assert chart.iloc[0]["账户总资产"] == 100000

