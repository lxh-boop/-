from __future__ import annotations

from pathlib import Path
from typing import Any

from database.repositories import UserRepository
from portfolio.schemas import InvestmentGoal, RiskAssessment, TradingBehavior, UserProfile
from portfolio.trading_permissions import (
    load_user_trading_permissions,
    normalize_trading_permissions,
)


PROFILE_CONSTRAINTS = {
    "保守型": {
        "max_single_position": 0.04,
        "max_industry_position": 0.20,
        "max_drawdown_tolerance": 0.08,
        "allow_high_volatility": False,
    },
    "稳健型": {
        "max_single_position": 0.08,
        "max_industry_position": 0.30,
        "max_drawdown_tolerance": 0.15,
        "allow_high_volatility": False,
    },
    "激进型": {
        "max_single_position": 0.12,
        "max_industry_position": 0.40,
        "max_drawdown_tolerance": 0.25,
        "allow_high_volatility": True,
    },
}


def normalize_profile_type(profile_type: str | None) -> str:
    text = str(profile_type or "").strip()
    if text in PROFILE_CONSTRAINTS:
        return text
    if text.lower() in {"conservative", "c1", "c2"}:
        return "保守型"
    if text.lower() in {"aggressive", "c5"}:
        return "激进型"
    return "稳健型"


def default_user_profile(user_id: str = "default_user", profile_type: str = "稳健型") -> UserProfile:
    profile_type = normalize_profile_type(profile_type)
    capital = 50000.0 if profile_type == "保守型" else 100000.0 if profile_type == "稳健型" else 200000.0
    experience = "1年以内" if profile_type == "保守型" else "1-3年" if profile_type == "稳健型" else "3年以上"
    liquidity = "高" if profile_type == "保守型" else "中" if profile_type == "稳健型" else "低"
    return UserProfile(
        user_id=user_id,
        profile_type=profile_type,
        available_capital=capital,
        investment_experience=experience,
        liquidity_need=liquidity,
    )


def default_risk_assessment(user_id: str, profile_type: str = "稳健型") -> RiskAssessment:
    profile_type = normalize_profile_type(profile_type)
    if profile_type == "保守型":
        return RiskAssessment(f"risk_{user_id}", user_id, 30.0, "C2", 0.08, volatility_tolerance="低", investment_horizon="短期")
    if profile_type == "激进型":
        return RiskAssessment(f"risk_{user_id}", user_id, 80.0, "C5", 0.25, volatility_tolerance="高", investment_horizon="长期")
    return RiskAssessment(f"risk_{user_id}", user_id, 55.0, "C3", 0.15, volatility_tolerance="中", investment_horizon="中期")


def default_investment_goal(user_id: str, profile_type: str = "稳健型") -> InvestmentGoal:
    profile_type = normalize_profile_type(profile_type)
    if profile_type == "保守型":
        return InvestmentGoal(f"goal_{user_id}", user_id, goal_type="现金管理", target_return=0.03, priority="风险优先", target_period="短期")
    if profile_type == "激进型":
        return InvestmentGoal(f"goal_{user_id}", user_id, goal_type="长期成长", target_return=0.12, priority="收益优先", target_period="长期")
    return InvestmentGoal(f"goal_{user_id}", user_id)


def build_user_constraints(
    profile: UserProfile,
    risk_assessment: RiskAssessment | None = None,
    investment_goal: InvestmentGoal | None = None,
    trading_behavior: TradingBehavior | None = None,
    trading_permissions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_type = normalize_profile_type(profile.profile_type)
    base = dict(PROFILE_CONSTRAINTS[profile_type])
    if risk_assessment:
        base["max_drawdown_tolerance"] = min(
            float(base["max_drawdown_tolerance"]),
            float(risk_assessment.max_drawdown_tolerance),
        )
        base["risk_level"] = risk_assessment.risk_level
        base["investment_horizon"] = risk_assessment.investment_horizon
    else:
        base["risk_level"] = "C3"
        base["investment_horizon"] = "中期"

    if investment_goal:
        base["goal_type"] = investment_goal.goal_type
        base["goal_priority"] = investment_goal.priority
        base["investment_horizon"] = investment_goal.target_period or base["investment_horizon"]
    else:
        base["goal_type"] = "稳健增值"
        base["goal_priority"] = "风险优先"

    base["profile_type"] = profile_type
    base["liquidity_need"] = profile.liquidity_need
    base["preferred_industries"] = list(trading_behavior.preferred_industries) if trading_behavior else []
    base["avoided_industries"] = []
    base["trading_permissions"] = normalize_trading_permissions(
        trading_permissions
    )
    return base


def _profile_type_from_risk_level(risk_level: str | None) -> str:
    if risk_level in {"C1", "C2"}:
        return "保守型"
    if risk_level in {"C4", "C5"}:
        return "激进型"
    return "稳健型"


def load_user_context(
    user_id: str,
    db_path: str | Path | None = None,
    default_profile_type: str = "稳健型",
    output_dir: str | Path = "outputs",
) -> tuple[UserProfile, RiskAssessment, InvestmentGoal, dict[str, Any]]:
    try:
        repo = UserRepository(db_path)
        profile_row = repo.get_user_profile(user_id)
        risk_rows = repo.list_risk_assessments(user_id)
        goal_rows = repo.list_investment_goals(user_id)
    except Exception:
        profile = default_user_profile(user_id, default_profile_type)
        risk = default_risk_assessment(user_id, profile.profile_type)
        goal = default_investment_goal(user_id, profile.profile_type)
        permissions = load_user_trading_permissions(
            user_id,
            output_dir,
        )
        return profile, risk, goal, build_user_constraints(
            profile,
            risk,
            goal,
            trading_permissions=permissions,
        )

    risk_row = risk_rows[-1] if risk_rows else None
    inferred_profile_type = _profile_type_from_risk_level(risk_row.get("risk_level") if risk_row else None)
    if profile_row:
        profile = UserProfile(
            user_id=profile_row["user_id"],
            profile_type=profile_row.get("profile_type") or inferred_profile_type,
            age_range=profile_row.get("age_range") or "",
            income_level=profile_row.get("income_level") or "",
            available_capital=float(profile_row.get("available_capital") or 100000.0),
            investment_experience=profile_row.get("investment_experience") or "1-3年",
            liquidity_need=profile_row.get("liquidity_need") or "中",
            created_at=profile_row.get("created_at") or "",
            updated_at=profile_row.get("updated_at") or "",
        )
    else:
        profile = default_user_profile(user_id, inferred_profile_type or default_profile_type)

    if risk_row:
        risk = RiskAssessment(
            assessment_id=risk_row["assessment_id"],
            user_id=risk_row["user_id"],
            risk_score=float(risk_row.get("risk_score") or 0.0),
            risk_level=risk_row.get("risk_level") or "C3",
            max_drawdown_tolerance=float(risk_row.get("max_drawdown_tolerance") or PROFILE_CONSTRAINTS[profile.profile_type]["max_drawdown_tolerance"]),
            single_loss_tolerance=float(risk_row.get("single_loss_tolerance") or 0.05),
            volatility_tolerance=risk_row.get("volatility_tolerance") or "中",
            investment_horizon=risk_row.get("investment_horizon") or "中期",
            questionnaire_version=risk_row.get("questionnaire_version") or "default_v1",
            assessment_time=risk_row.get("assessment_time") or "",
            is_valid=bool(risk_row.get("is_valid", 1)),
        )
    else:
        risk = default_risk_assessment(user_id, profile.profile_type)

    goal_row = goal_rows[-1] if goal_rows else None
    if goal_row:
        goal = InvestmentGoal(
            goal_id=goal_row["goal_id"],
            user_id=goal_row["user_id"],
            goal_type=goal_row.get("goal_type") or "稳健增值",
            target_return=float(goal_row.get("target_return") or 0.06),
            target_period=goal_row.get("target_period") or risk.investment_horizon,
            priority=goal_row.get("priority") or "风险优先",
            capital_usage=goal_row.get("capital_usage") or "闲置资金",
            created_at=goal_row.get("created_at") or "",
            updated_at=goal_row.get("updated_at") or "",
        )
    else:
        goal = default_investment_goal(user_id, profile.profile_type)

    permissions = load_user_trading_permissions(
        user_id,
        output_dir,
    )
    return profile, risk, goal, build_user_constraints(
        profile,
        risk,
        goal,
        trading_permissions=permissions,
    )
