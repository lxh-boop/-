from app.pages import ai_paper_trading


def test_account_summary_sections_include_three_row_metrics() -> None:
    sections = ai_paper_trading.get_ai_paper_trading_page_sections()

    assert "用户与账户摘要" in sections
    assert hasattr(ai_paper_trading, "AI_PAPER_TRADING_PAGE_TITLE")
