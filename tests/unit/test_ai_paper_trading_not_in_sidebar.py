from pathlib import Path


def test_ai_paper_trading_is_not_sidebar_navigation() -> None:
    source = Path("app.py").read_text(encoding="utf-8")

    assert 'APP_TOP_LEVEL_PAGES = ["首页 / 预测排名", "AI 模拟盘", "AI Agent", "系统监控"]' in source
    assert 'st.radio("页面"' in source
    assert "st.sidebar.radio(\"页面\"" not in source
    assert "render_ai_paper_trading_page" in source
