from app.pages.ai_paper_trading import build_capital_summary_rows, get_ai_paper_trading_page_sections


def test_compact_account_summary_includes_complete_values() -> None:
    rows = build_capital_summary_rows(
        {
            "cash": 150000,
            "total_assets": 160000,
            "position_market_value": 10000,
            "initial_cash": 100000,
            "cumulative_deposit": 50000,
            "cumulative_fee": 123.45,
            "net_contribution": 150000,
            "time_weighted_return": 0.1234,
        },
        {"cash_ratio": 0.5, "risk_level": "low"},
        {"ai_reliability_weight": 0.0},
        "cht",
        {"capital_utilization_rate": 0.88},
    )

    values = [item["value"] for row in rows for item in row]

    assert "150,000.00" in values
    assert "2026-" in values[1]
    assert "..." not in "".join(values)
    assert "资金分配详情" in get_ai_paper_trading_page_sections()

