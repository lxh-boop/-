from __future__ import annotations

from typing import Any

from portfolio.paper_account import account_from_dict
from portfolio.paper_position import position_from_dict
from portfolio.schemas import PaperAccount, PaperPosition, PortfolioRiskReport
from portfolio.user_profile import PROFILE_CONSTRAINTS


HIGH_RISK_LEVELS = {"high", "very_high", "extreme", "C5"}


def _as_account(account: PaperAccount | dict[str, Any] | None) -> PaperAccount:
    if account is None:
        return PaperAccount(account_id="paper_default", user_id="default_user")
    if isinstance(account, PaperAccount):
        return account
    return account_from_dict(account)


def _as_position(position: PaperPosition | dict[str, Any], total_assets: float) -> PaperPosition:
    if isinstance(position, PaperPosition):
        return position
    return position_from_dict(position, total_assets=total_assets)


def _position_ratio(position: PaperPosition, total_assets: float) -> float:
    if position.position_ratio:
        return float(position.position_ratio)
    if total_assets <= 0:
        return 0.0
    return float(position.market_value) / total_assets


def _risk_level_from_warnings(warning_count: int, drawdown_exceeded: bool) -> str:
    if drawdown_exceeded and warning_count >= 3:
        return "extreme"
    if warning_count >= 2 or drawdown_exceeded:
        return "high"
    if warning_count == 1:
        return "medium"
    return "low"


def calculate_portfolio_risk(
    user_id: str,
    account: PaperAccount | dict[str, Any] | None = None,
    positions: list[PaperPosition | dict[str, Any]] | None = None,
    constraints: dict[str, Any] | None = None,
) -> PortfolioRiskReport:
    """Calculate first-version paper portfolio risk against user constraints."""

    account_obj = _as_account(account)
    total_assets = float(account_obj.total_assets or account_obj.cash or account_obj.initial_cash or 0.0)
    raw_positions = positions or []
    position_objs = [_as_position(item, total_assets=total_assets) for item in raw_positions]
    invested_value = sum(max(0.0, float(item.market_value)) for item in position_objs)
    if total_assets <= 0:
        total_assets = float(account_obj.cash) + invested_value

    cash_ratio = float(account_obj.cash) / total_assets if total_assets > 0 else 0.0
    ratios = [_position_ratio(item, total_assets) for item in position_objs if item.quantity > 0]
    max_single_position = max(ratios, default=0.0)

    industry_concentration: dict[str, float] = {}
    for item in position_objs:
        if item.quantity <= 0:
            continue
        industry = item.industry or "unknown"
        industry_concentration[industry] = industry_concentration.get(industry, 0.0) + _position_ratio(item, total_assets)

    high_risk_position_ratio = 0.0
    for raw, item in zip(raw_positions, position_objs):
        risk_level = ""
        if isinstance(raw, dict):
            risk_level = str(raw.get("risk_level") or "").strip()
        if risk_level in HIGH_RISK_LEVELS:
            high_risk_position_ratio += _position_ratio(item, total_assets)

    constraints = constraints or dict(PROFILE_CONSTRAINTS["稳健型"])
    max_single_limit = float(constraints.get("max_single_position", 0.08))
    max_industry_limit = float(constraints.get("max_industry_position", 0.30))
    max_drawdown_limit = float(constraints.get("max_drawdown_tolerance", 0.15))
    allow_high_volatility = bool(constraints.get("allow_high_volatility", False))
    drawdown = abs(min(0.0, float(account_obj.max_drawdown or 0.0)))

    warnings: list[str] = []
    if max_single_position > max_single_limit:
        warnings.append(f"单股仓位 {max_single_position:.2%} 超过用户限制 {max_single_limit:.2%}")
    max_industry_position = max(industry_concentration.values(), default=0.0)
    if max_industry_position > max_industry_limit:
        warnings.append(f"行业集中度 {max_industry_position:.2%} 超过用户限制 {max_industry_limit:.2%}")
    drawdown_exceeded = drawdown > max_drawdown_limit
    if drawdown_exceeded:
        warnings.append(f"最大回撤 {drawdown:.2%} 超过用户承受范围 {max_drawdown_limit:.2%}")
    if high_risk_position_ratio > 0 and not allow_high_volatility:
        warnings.append(f"高风险持仓占比 {high_risk_position_ratio:.2%} 与用户风险等级不匹配")

    return PortfolioRiskReport(
        user_id=user_id,
        total_assets=total_assets,
        cash_ratio=cash_ratio,
        max_single_position=max_single_position,
        industry_concentration=industry_concentration,
        max_drawdown=drawdown,
        holding_count=sum(1 for item in position_objs if item.quantity > 0),
        high_risk_position_ratio=high_risk_position_ratio,
        user_risk_match=not warnings,
        risk_level=_risk_level_from_warnings(len(warnings), drawdown_exceeded),
        risk_warnings=warnings,
        is_paper_trading=True,
    )
