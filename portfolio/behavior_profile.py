from __future__ import annotations

from portfolio.schemas import TradingBehavior


def classify_trading_style(behavior: TradingBehavior) -> str:
    if behavior.avg_holding_days <= 5 or behavior.turnover_rate >= 1.0:
        return "短线"
    if behavior.avg_holding_days >= 90 and behavior.turnover_rate <= 0.2:
        return "长期"
    return "中线"


def behavior_risk_warning(behavior: TradingBehavior, risk_level: str) -> str:
    style = classify_trading_style(behavior)
    if risk_level in {"C1", "C2"} and (style == "短线" or behavior.max_historical_loss > 0.1):
        return "用户交易行为风险高于风险测评结果，应降低模拟盘仓位。"
    return ""
