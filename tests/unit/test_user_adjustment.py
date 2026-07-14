from __future__ import annotations

from scoring.user_adjustment import calculate_user_adjustment


def test_conservative_user_high_risk_stock_is_down_weighted() -> None:
    result = calculate_user_adjustment(
        {"user_id": "u1", "profile_type": "conservative", "risk_level": "C2"},
        stock_risk_level="high",
    )

    assert result.forced_action == "down_weight"
    assert result.user_adjustment_score < 0
    assert result.target_weight_cap <= 0.05
    assert result.high_risk_adjustment_ratio < result.normal_risk_adjustment_ratio


def test_avoided_industry_is_down_weight_or_exclude() -> None:
    result = calculate_user_adjustment(
        {"avoided_industries": ["coal"], "profile_type": "balanced"},
        stock_risk_level="medium",
        stock_industry="coal",
    )

    assert result.forced_action == "down_weight"
    assert result.user_adjustment_score < 0


def test_preferred_industry_bonus_is_small_and_does_not_override_risk() -> None:
    preferred = calculate_user_adjustment(
        {"preferred_industries": ["bank"], "profile_type": "balanced"},
        stock_risk_level="low",
        stock_industry="bank",
    )
    high_risk = calculate_user_adjustment(
        {"preferred_industries": ["bank"], "profile_type": "conservative", "risk_level": "C2"},
        stock_risk_level="high",
        stock_industry="bank",
    )

    assert 0 < preferred.user_adjustment_score <= 0.05
    assert high_risk.forced_action == "down_weight"
