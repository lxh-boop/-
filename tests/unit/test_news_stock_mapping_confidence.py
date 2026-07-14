from __future__ import annotations

import math

from database.repositories import NewsRepository
from database.schemas import calculate_mapping_confidence


def test_mapping_confidence_formula_matches_design_document() -> None:
    score = calculate_mapping_confidence(
        entity_score=0.9,
        event_score=0.8,
        industry_score=0.7,
        source_score=0.6,
        position_score=0.5,
        llm_score=0.4,
        penalty=0.1,
        clamp=False,
    )

    expected = (
        0.35 * 0.9
        + 0.20 * 0.8
        + 0.15 * 0.7
        + 0.10 * 0.6
        + 0.10 * 0.5
        + 0.10 * 0.4
        - 0.1
    )
    assert math.isclose(score, expected)


def test_mapping_confidence_is_clamped_by_default() -> None:
    assert calculate_mapping_confidence(entity_score=10.0) == 1.0
    assert calculate_mapping_confidence(penalty=10.0) == 0.0


def test_news_repository_computes_mapping_confidence(tmp_path) -> None:
    repo = NewsRepository(tmp_path / "agent_quant.db")

    repo.insert_news_stock_mapping(
        {
            "mapping_id": "mapping_001",
            "news_id": "news_001",
            "stock_code": "300750",
            "stock_name": "宁德时代",
            "impact_direction": "negative",
            "entity_score": 1.0,
            "event_score": 0.8,
            "industry_score": 0.6,
            "source_score": 0.5,
            "position_score": 0.5,
            "llm_score": 0.5,
            "penalty": 0.0,
            "evidence_text": "公告直接提到公司。",
        }
    )

    row = repo.get_news_stock_mapping("mapping_001")
    assert row is not None
    assert row["mapping_confidence"] > 0.6
