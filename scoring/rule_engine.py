from __future__ import annotations

from dataclasses import dataclass, field

from scoring.news_adjustment import NewsAdjustmentResult
from scoring.normalizers import clamp, normalize_confidence
from scoring.schemas import (
    AgentRuleSignal,
    ModelPredictionSignal,
    PortfolioConstraintSignal,
    TriggeredRule,
    UserConstraintSignal,
)


ACTION_PRIORITY = {"keep": 0, "down_weight": 1, "risk_alert": 2, "hold": 3, "exclude": 4}


@dataclass(frozen=True)
class RuleEngineResult:
    triggered_rules: list[TriggeredRule] = field(default_factory=list)
    rule_penalty_score: float = 0.0
    forced_action: str | None = None


def _is_conservative(user: UserConstraintSignal) -> bool:
    text = f"{user.profile_type} {user.risk_level}".lower()
    return any(token in text for token in ["conservative", "c1", "c2", "保守"])


def _is_high_risk(value: str) -> bool:
    text = str(value or "").lower()
    return text in {"high", "very_high", "extreme", "r4", "r5", "c5"} or "高" in text or "极" in text


def _select_forced_action(actions: list[str | None]) -> str | None:
    valid = [action for action in actions if action]
    if not valid:
        return None
    return max(valid, key=lambda action: ACTION_PRIORITY.get(str(action), -1))


def evaluate_rules(
    model_signal: ModelPredictionSignal,
    user_constraints: UserConstraintSignal,
    portfolio_constraints: PortfolioConstraintSignal,
    news_adjustment: NewsAdjustmentResult,
    agent_rules: list[AgentRuleSignal] | None = None,
) -> RuleEngineResult:
    triggered: list[TriggeredRule] = []

    def add(rule_id: str, name: str, reason: str, penalty: float, forced: str | None = None) -> None:
        triggered.append(
            TriggeredRule(
                rule_id=rule_id,
                rule_name=name,
                reason=reason,
                penalty_score=penalty,
                forced_action=forced,
            )
        )

    if _is_conservative(user_constraints) and _is_high_risk(model_signal.risk_level):
        add(
            "risk_level_mismatch",
            "Risk level mismatch",
            "User C1/C2 profile receives reduced target weight for R4/R5 or high-risk assets.",
            -0.30,
            "down_weight",
        )

    if portfolio_constraints.industry_position_ratio > portfolio_constraints.max_industry_position:
        add(
            "industry_concentration",
            "Industry concentration",
            "Industry position exceeds configured threshold.",
            -0.20,
            "down_weight",
        )

    if news_adjustment.major_negative or news_adjustment.news_adjustment_score <= -0.20:
        add(
            "major_negative_news",
            "Major negative news",
            "High-confidence negative news evidence triggers a rule penalty.",
            -0.35,
            "risk_alert" if news_adjustment.major_negative else "down_weight",
        )

    if normalize_confidence(model_signal.confidence) <= 0.25:
        add(
            "low_confidence_prediction",
            "Low confidence prediction",
            "Low model confidence only allows watchlist.",
            -0.20,
            "hold",
        )

    if str(user_constraints.liquidity_need).lower() in {"high", "very_high"} and portfolio_constraints.volatility >= 0.40:
        add(
            "high_liquidity_need",
            "High liquidity need",
            "High liquidity need lowers high-volatility exposure.",
            -0.10,
            "down_weight",
        )

    if "st" in model_signal.stock_name.lower() or str(model_signal.risk_level).lower() in {"extreme", "r5"}:
        add(
            "extreme_or_st_asset",
            "ST or extreme risk asset",
            "ST or extreme-risk assets are excluded by default.",
            -0.50,
            "exclude",
        )

    for rule in sorted(agent_rules or [], key=lambda item: item.priority):
        if not rule.is_active:
            continue
        if rule.action in {"exclude", "down_weight", "hold", "risk_alert"} and rule.condition.get("always"):
            add(
                rule.rule_id,
                rule.rule_name or "Agent configured rule",
                "Active configured agent rule matched.",
                -0.05,
                rule.action,
            )

    forced = _select_forced_action([rule.forced_action for rule in triggered])
    return RuleEngineResult(
        triggered_rules=triggered,
        rule_penalty_score=clamp(sum(rule.penalty_score for rule in triggered), -0.80, 0.0),
        forced_action=forced,
    )
