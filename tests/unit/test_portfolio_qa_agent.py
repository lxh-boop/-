from __future__ import annotations

import json

from agent.portfolio_qa_agent import PortfolioQAAgent
from database.repositories import AgentRepository, NewsRepository


def test_portfolio_qa_agent_uses_recommendation_decision_and_evidence(tmp_path) -> None:
    rec_dir = tmp_path / "recommendations"
    rec_dir.mkdir()
    (rec_dir / "final_recommendations_latest.json").write_text(
        json.dumps(
            [
                {
                    "stock_code": "000001",
                        "stock_name": "Ping An Bank",
                        "original_pred_score": 0.9,
                        "original_pred_rank": 1,
                        "news_adjustment": -0.1,
                        "effective_news_adjustment": -0.05,
                        "user_adjustment": 0,
                        "combined_adjustment": -0.05,
                        "position_adjustment_ratio": 0.95,
                        "confidence": "medium",
                        "triggered_rules": ["risk_rule"],
                    "reason": "policy risk",
                }
            ]
        ),
        encoding="utf-8",
    )
    db_path = tmp_path / "agent_quant.db"
    NewsRepository(db_path).insert_news_chunk(
        {
            "chunk_id": "chunk_1",
            "news_id": "news_1",
            "chunk_index": 0,
            "chunk_text": "policy risk for bank",
            "stock_code": "000001",
            "trade_date": "2026-06-11",
        }
    )
    AgentRepository(db_path).insert_decision_log(
        {
            "decision_id": "decision_1",
            "user_id": "default",
            "trade_date": "2026-06-11",
            "stock_code": "000001",
            "combined_adjustment": -0.05,
            "position_adjustment_ratio": 0.95,
            "evidence_chunk_ids": ["chunk_1"],
        }
    )

    result = PortfolioQAAgent().answer("why numeric adjustment 000001 policy", trade_date="2026-06-11", output_dir=tmp_path, db_path=db_path)
    assert result["agent"] == "portfolio_qa"
    assert "combined adjustment: -0.05" in result["answer"]
    assert "Position adjustment ratio: 0.95" in result["answer"]
    assert "chunk_1" in result["answer"]
    assert "not real buy/sell instructions" in result["answer"]
