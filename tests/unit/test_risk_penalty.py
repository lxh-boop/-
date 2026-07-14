from __future__ import annotations

from scoring.risk_penalty import calculate_risk_penalty


def test_single_position_limit_triggers_down_weight() -> None:
    result = calculate_risk_penalty(
        {
            "current_position_ratio": 0.20,
            "max_single_position": 0.08,
            "max_industry_position": 0.30,
        }
    )

    assert result.risk_penalty_score < 0
    assert result.risk_penalty_score <= 0
    assert result.forced_action == "down_weight"


def test_industry_limit_triggers_watchlist_or_down_weight() -> None:
    result = calculate_risk_penalty(
        {
            "industry_position_ratio": 0.40,
            "max_industry_position": 0.30,
        }
    )

    assert result.risk_penalty_score < 0
    assert result.forced_action in {"hold", "down_weight"}


def test_low_confidence_only_allows_watchlist() -> None:
    result = calculate_risk_penalty({"confidence": "low"})

    assert result.forced_action is None
    assert result.risk_penalty_score <= 0
