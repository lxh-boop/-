from pathlib import Path


def test_paper_page_does_not_duplicate_home_prediction_explanation() -> None:
    source = Path("app/pages/ai_paper_trading.py").read_text(encoding="utf-8")
    forbidden = [
        "原始 K线排名为什么高",
        "新闻/RAG 对它做了什么修正",
        "AI 为什么保留",
        "AI 为什么降权",
        "AI 为什么剔除",
    ]

    for text in forbidden:
        assert text not in source

    assert "调仓理由" in source
    assert "组合风险" in source
