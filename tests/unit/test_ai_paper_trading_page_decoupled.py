from pathlib import Path


def test_ai_paper_trading_page_does_not_call_daily_update_pipeline() -> None:
    source = Path("app/pages/ai_paper_trading.py").read_text(encoding="utf-8")

    assert "run_daily_update_pipeline" not in source
    assert "run_paper_trading_from_latest" in source
    assert "未调用模型生成" in source
