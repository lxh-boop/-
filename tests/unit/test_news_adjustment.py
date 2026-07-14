from __future__ import annotations

from scoring.news_adjustment import calculate_news_adjustment


def test_news_adjustment_is_clamped_to_expected_range() -> None:
    result = calculate_news_adjustment(
        [
            {
                "news_id": "news_001",
                "impact_direction": "negative",
                "impact_strength": 1.0,
                "impact_confidence": 1.0,
                "mapping_confidence": 1.0,
                "importance_score": 1.0,
                "publish_time": "2026-06-11 10:00:00",
                "trade_date": "2026-06-11",
                "evidence_chunk_ids": ["chunk_001"],
            },
            {
                "news_id": "news_002",
                "impact_direction": "negative",
                "impact_strength": 1.0,
                "impact_confidence": 1.0,
                "mapping_confidence": 1.0,
                "importance_score": 1.0,
                "publish_time": "2026-06-11 10:30:00",
                "trade_date": "2026-06-11",
            },
        ]
    )

    assert -0.30 <= result.news_adjustment_score <= 0.30
    assert result.news_adjustment_score == -0.30
    assert result.major_negative is True
    assert result.evidence_chunk_ids == ["chunk_001"]


def test_no_or_low_confidence_news_does_not_penalize() -> None:
    assert calculate_news_adjustment(None).news_adjustment_score == 0
    result = calculate_news_adjustment(
        {
            "news_id": "news_low",
            "impact_direction": "negative",
            "impact_strength": 1.0,
            "impact_confidence": 0.2,
            "mapping_confidence": 0.9,
        }
    )

    assert result.news_adjustment_score == 0


def test_after_close_news_is_not_used_for_same_day_decision() -> None:
    result = calculate_news_adjustment(
        {
            "news_id": "news_after_close",
            "impact_direction": "negative",
            "impact_strength": 1.0,
            "impact_confidence": 1.0,
            "mapping_confidence": 1.0,
            "publish_time": "2026-06-11 15:01:00",
            "trade_date": "2026-06-11",
        },
        trade_date="2026-06-11",
    )

    assert result.news_adjustment_score == 0
    assert result.evidence_news_ids == []


def test_future_assigned_trade_date_is_not_used_for_earlier_signal() -> None:
    result = calculate_news_adjustment(
        {
            "news_id": "news_future",
            "impact_direction": "negative",
            "impact_strength": 1.0,
            "impact_confidence": 1.0,
            "mapping_confidence": 1.0,
            "publish_time": "2026-06-12 09:30:00",
            "trade_date": "2026-06-12",
        },
        trade_date="2026-06-11",
    )

    assert result.news_adjustment_score == 0
    assert result.evidence_news_ids == []
