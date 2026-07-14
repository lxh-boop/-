from __future__ import annotations

from portfolio.user_profile import (
    build_user_constraints,
    default_risk_assessment,
    default_user_profile,
    load_user_context,
)


def test_default_user_profile_is_balanced() -> None:
    profile = default_user_profile("user_001")
    risk = default_risk_assessment(profile.user_id, profile.profile_type)
    constraints = build_user_constraints(profile, risk)

    assert profile.profile_type == "稳健型"
    assert constraints["max_single_position"] == 0.08
    assert constraints["max_industry_position"] == 0.30
    assert constraints["allow_high_volatility"] is False


def test_profile_constraints_differ_by_type() -> None:
    conservative = build_user_constraints(default_user_profile("u1", "保守型"))
    balanced = build_user_constraints(default_user_profile("u2", "稳健型"))
    aggressive = build_user_constraints(default_user_profile("u3", "激进型"))

    assert conservative["max_single_position"] < balanced["max_single_position"]
    assert balanced["max_single_position"] < aggressive["max_single_position"]
    assert conservative["allow_high_volatility"] is False
    assert aggressive["allow_high_volatility"] is True


def test_load_user_context_falls_back_to_default_profile(tmp_path) -> None:
    profile, risk, goal, constraints = load_user_context(
        "missing_user",
        db_path=tmp_path / "agent_quant.db",
    )

    assert profile.user_id == "missing_user"
    assert profile.profile_type == "稳健型"
    assert risk.risk_level == "C3"
    assert goal.user_id == "missing_user"
    assert constraints["liquidity_need"] == profile.liquidity_need
