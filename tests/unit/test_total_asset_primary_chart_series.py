from app.pages.ai_paper_trading import ASSET_CURVE_COLUMNS, ASSET_CURVE_TITLE


def test_total_asset_primary_chart_series() -> None:
    assert ASSET_CURVE_TITLE == "账户资产走势"
    assert list(ASSET_CURVE_COLUMNS.values())[0] == "账户总资产"
    assert list(ASSET_CURVE_COLUMNS.values()) == ["账户总资产", "净投入资金", "持仓市值", "现金"]
