from __future__ import annotations

from agent.event_impact_agent import EventImpactAgent
from database.repositories import NewsRepository


def test_event_impact_agent_reports_mapping_and_uncertainty(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    repo = NewsRepository(db_path)
    repo.insert_news_chunk(
        {
            "chunk_id": "chunk_1",
            "news_id": "news_1",
            "chunk_index": 0,
            "chunk_text": "policy event affects battery supply",
            "stock_code": "300750",
            "industry": "battery",
            "event_type": "policy",
            "trade_date": "2026-06-11",
        }
    )
    repo.insert_news_stock_mapping(
        {
            "mapping_id": "mapping_1",
            "news_id": "news_1",
            "stock_code": "300750",
            "industry": "battery",
            "impact_direction": "negative",
            "mapping_confidence": 0.8,
        }
    )
    repo.insert_industry_event_rule(
        {
            "rule_id": "rule_1",
            "event_keyword": "policy",
            "affected_industry": "battery",
            "impact_direction": "negative",
        }
    )

    result = EventImpactAgent().answer("policy", stock_code="300750", trade_date="2026-06-11", db_path=db_path)
    assert result["agent"] == "event_impact"
    assert "300750" in result["answer"]
    assert "Uncertainty" in result["answer"]
    assert "not a buy/sell instruction" in result["risk_warning"]
