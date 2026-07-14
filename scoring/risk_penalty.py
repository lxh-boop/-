from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scoring.normalizers import clamp, normalize_confidence, safe_float
from scoring.schemas import PortfolioConstraintSignal


@dataclass(frozen=True)
class RiskPenaltyResult:
    risk_penalty_score: float = 0.0
    forced_action: str | None = None
    reason: str = "Portfolio risk constraints are neutral."
    risk_warning: str = ""


def _is_high_risk(value: str) -> bool:
    text = str(value or "").lower()
    return text in {"high", "very_high", "extreme", "r4", "r5", "c5"} or "高" in text or "极" in text


def calculate_risk_penalty(
    portfolio_constraints: PortfolioConstraintSignal | dict[str, Any] | None,
) -> RiskPenaltyResult:
    portfolio = (
        portfolio_constraints
        if isinstance(portfolio_constraints, PortfolioConstraintSignal)
        else PortfolioConstraintSignal.from_mapping(portfolio_constraints)
    )
    penalty = 0.0
    forced_action: str | None = None
    reasons: list[str] = []
    warnings: list[str] = []

    if portfolio.current_position_ratio > portfolio.max_single_position:
        penalty -= 0.25
        forced_action = "down_weight"
        reasons.append("Current single-stock position exceeds max_single_position.")
        warnings.append("Single-stock concentration limit exceeded.")

    if portfolio.industry_position_ratio > portfolio.max_industry_position:
        penalty -= 0.20
        forced_action = forced_action or "down_weight"
        reasons.append("Industry position exceeds max_industry_position.")
        warnings.append("Industry concentration limit exceeded; target weight should be reduced.")

    if str(portfolio.portfolio_risk_level).lower() in {"high", "extreme"} and _is_high_risk(portfolio.stock_risk_level):
        penalty -= 0.25
        forced_action = forced_action or "risk_alert"
        reasons.append("High-risk portfolio cannot expand high-risk exposure.")
        warnings.append("Portfolio risk level is already high; new exposure should be limited.")

    if normalize_confidence(portfolio.confidence) <= 0.25:
        penalty -= 0.15
        forced_action = None
        reasons.append("Low model confidence applies a small position.")
        warnings.append("Model prediction confidence is low.")

    if safe_float(portfolio.volatility, 0.0) >= 0.60:
        penalty -= 0.08
        reasons.append("High volatility adds a risk penalty.")

    if abs(min(0.0, safe_float(portfolio.drawdown, 0.0))) >= 0.15:
        penalty -= 0.08
        reasons.append("Drawdown adds a risk penalty.")

    return RiskPenaltyResult(
        risk_penalty_score=clamp(penalty, -0.60, 0.0),
        forced_action=forced_action,
        reason="; ".join(reasons) if reasons else "Portfolio risk constraints are neutral.",
        risk_warning="; ".join(warnings),
    )
