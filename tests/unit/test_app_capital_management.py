from app.pages.ai_paper_trading import build_capital_summary_rows, build_cash_flow_table, get_ai_paper_trading_page_sections


def test_ai_paper_page_contains_capital_management_section() -> None:
    assert "资金管理" in get_ai_paper_trading_page_sections()
    assert "历史回放" in get_ai_paper_trading_page_sections()


def test_cash_flow_table_formats_amounts() -> None:
    table = build_cash_flow_table(
        [
            {
                "effective_date": "2026-05-04",
                "flow_type": "deposit",
                "amount": 50000,
                "status": "pending",
                "reason": "test",
                "created_at": "now",
                "cash_flow_id": "cf1",
            }
        ]
    )

    assert table.iloc[0]["类型"] == "追加资金"
    assert table.iloc[0]["金额"] == "50,000.00"


def test_capital_summary_includes_twr_and_net_contribution() -> None:
    rows = build_capital_summary_rows(
        {"cash": 150000, "total_assets": 160000, "initial_cash": 100000, "cumulative_deposit": 50000, "net_contribution": 150000, "time_weighted_return": 0.1},
        {"cash_ratio": 0.5, "risk_level": "low"},
        {"ai_reliability_weight": 0.0},
        "u1",
    )

    labels = [item["label"] for row in rows for item in row]
    assert "净投入资金" in labels
    assert "时间加权收益率" in labels
