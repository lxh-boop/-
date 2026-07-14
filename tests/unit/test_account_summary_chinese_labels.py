from app.pages.ai_paper_trading import build_capital_summary_rows


def test_account_summary_labels_are_chinese() -> None:
    rows = build_capital_summary_rows(
        {
            "cash": 10000,
            "total_assets": 120000,
            "position_market_value": 110000,
            "initial_cash": 100000,
            "cumulative_deposit": 50000,
            "net_contribution": 150000,
            "composite_nav": 1.02,
        },
        {"cash_ratio": 0.08, "risk_level": "medium"},
        {"ai_reliability_weight": 0.0},
        "u1",
        {"capital_utilization_rate": 0.9},
    )

    labels = [item["label"] for row in rows for item in row]
    assert "用户编号" in labels
    assert "当前现金" in labels
    assert "当前总资产" in labels
    assert "综合净值" in labels
    assert "AI 修正可靠度" in labels
    assert not any(label in {"user_id", "current_cash", "total_assets", "portfolio_risk"} for label in labels)
