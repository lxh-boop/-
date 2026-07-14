import pandas as pd

from app.classic_services import build_ai_adjustment_detail


def test_ai_adjustment_reason_and_evidence_are_visible() -> None:
    row = pd.Series(
        {
            "pred_score": 0.9,
            "pred_rank": 1,
            "news_adjustment_score": -0.1,
            "user_adjustment_score": 0.0,
            "risk_penalty_score": -0.05,
            "triggered_rules": "risk_rule",
            "evidence_news_ids": "news_001",
            "evidence_chunk_ids": "chunk_001",
            "final_action": "risk_alert",
            "reason": "Negative event increased risk.",
            "risk_warning": "High volatility.",
        }
    )

    detail = build_ai_adjustment_detail(row)

    assert detail["reason"] == "Negative event increased risk."
    assert detail["risk_warning"] == "High volatility."
    assert detail["evidence_news_ids"] == "news_001"
    assert detail["evidence_chunk_ids"] == "chunk_001"


def test_missing_news_evidence_is_not_fabricated() -> None:
    detail = build_ai_adjustment_detail({"pred_score": 0.5, "pred_rank": 3})

    assert "未检索到相关新闻证据" in detail["evidence_news_ids"]
