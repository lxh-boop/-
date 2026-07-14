from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring.normalizers import clamp, safe_float
from scoring.schemas import UserConstraintSignal


@dataclass(frozen=True)
class UserAdjustmentResult:
    user_adjustment_score: float = 0.0
    forced_action: str | None = None
    reason: str = "User suitability constraints are neutral."
    risk_warning: str = ""
    target_weight_cap: float = 0.08
    normal_risk_adjustment_ratio: float = 0.90
    high_risk_adjustment_ratio: float = 0.60


def _is_conservative(user: UserConstraintSignal) -> bool:
    text = f"{user.profile_type} {user.risk_level}".lower()
    return any(token in text for token in ["conservative", "c1", "c2", "保守"])


def _is_aggressive(user: UserConstraintSignal) -> bool:
    text = f"{user.profile_type} {user.risk_level}".lower()
    return any(token in text for token in ["aggressive", "c4", "c5", "激进"])


def _is_high_risk(value: str) -> bool:
    text = str(value or "").lower()
    return text in {"high", "very_high", "extreme", "r4", "r5", "c5"} or "高" in text or "极" in text


def _is_high_liquidity(value: str) -> bool:
    text = str(value or "").lower()
    return text in {"high", "very_high"} or "高" in text


def risk_profile_position_limits(user: UserConstraintSignal) -> tuple[float, float, float]:
    text = f"{user.profile_type} {user.risk_level}".lower()
    if "c1" in text or "保守" in text and "偏" not in text:
        return 0.03, 0.70, 0.40
    if "c2" in text or "稳健偏保守" in text:
        return 0.05, 0.80, 0.50
    if "c4" in text or "积极" in text:
        return 0.10, 0.95, 0.70
    if "c5" in text or "激进" in text:
        return 0.15, 1.00, 0.85
    return 0.08, 0.90, 0.60


def calculate_user_adjustment(
    user_constraints: UserConstraintSignal | dict[str, Any] | None,
    stock_risk_level: str = "medium",
    stock_industry: str = "",
    volatility: float = 0.0,
) -> UserAdjustmentResult:
    user = user_constraints if isinstance(user_constraints, UserConstraintSignal) else UserConstraintSignal.from_mapping(user_constraints)
    score = 0.0
    forced_action: str | None = None
    reasons: list[str] = []
    warnings: list[str] = []
    profile_cap, normal_ratio, high_ratio = risk_profile_position_limits(user)
    target_cap = min(float(user.max_single_position), profile_cap)

    high_risk = _is_high_risk(stock_risk_level)
    if _is_conservative(user):
        if high_risk:
            score -= 0.25
            forced_action = "down_weight"
            reasons.append("Conservative user receives a smaller target weight for high-risk assets.")
            warnings.append("Risk level does not match conservative user profile; position is reduced instead of excluded.")
    elif _is_aggressive(user):
        if high_risk and user.allow_high_volatility:
            score -= 0.03
            reasons.append("Aggressive user allows high-risk assets with controlled position size.")
    else:
        if high_risk:
            score -= 0.15
            forced_action = "down_weight"
            reasons.append("Balanced user receives lower score for high-risk asset.")
            warnings.append("High-risk asset should be down-weighted for balanced profile.")

    if stock_industry and stock_industry in set(user.avoided_industries):
        score -= 0.20
        forced_action = "down_weight"
        if high_risk:
            score -= 0.05
        reasons.append("Stock industry is in avoided_industries.")
        warnings.append("User profile avoids this industry; only hard-risk cases can be excluded.")

    if stock_industry and stock_industry in set(user.preferred_industries) and not forced_action:
        score += 0.05
        reasons.append("Stock industry is in preferred_industries; small suitability bonus applied.")

    if _is_high_liquidity(user.liquidity_need) and safe_float(volatility, 0.0) >= 0.40:
        score -= 0.10
        forced_action = forced_action or "down_weight"
        reasons.append("High liquidity need reduces high-volatility stock suitability.")
        warnings.append("Liquidity need conflicts with high volatility.")

    return UserAdjustmentResult(
        user_adjustment_score=clamp(score, -0.30, 0.10),
        forced_action=forced_action,
        reason="; ".join(reasons) if reasons else "User suitability constraints are neutral.",
        risk_warning="; ".join(warnings),
        target_weight_cap=max(0.0, min(target_cap, float(user.max_single_position))),
        normal_risk_adjustment_ratio=normal_ratio,
        high_risk_adjustment_ratio=high_ratio,
    )
