from __future__ import annotations

from typing import Any


ACCOUNT_SUMMARY_LABELS: dict[str, str] = {
    "user_id": "用户编号",
    "paper_trading_start_date": "模拟起始日期",
    "start_date": "模拟起始日期",
    "current_cash": "当前现金",
    "cash": "当前现金",
    "total_asset": "当前总资产",
    "total_assets": "当前总资产",
    "position_market_value": "持仓市值",
    "position_value": "持仓市值",
    "initial_cash": "初始资金",
    "cumulative_deposit": "累计入金",
    "cumulative_withdrawal": "累计出金",
    "net_contribution": "净投入资金",
    "absolute_profit": "绝对盈亏",
    "time_weighted_return": "时间加权收益率",
    "daily_return": "今日收益率",
    "maximum_drawdown": "最大回撤",
    "max_drawdown": "最大回撤",
    "cash_ratio": "现金比例",
    "capital_utilization_rate": "资金利用率",
    "capital_utilization": "资金利用率",
    "portfolio_risk_level": "组合风险等级",
    "portfolio_risk": "组合风险等级",
    "ai_reliability": "AI 修正可靠度",
    "ai_reliability_weight": "AI 修正可靠度",
    "cumulative_fee": "累计手续费",
    "composite_nav": "综合净值",
}

RISK_LEVEL_LABELS: dict[str, str] = {
    "low": "低风险",
    "medium": "中等风险",
    "high": "高风险",
    "very_high": "极高风险",
    "extreme": "极高风险",
    "unknown": "未知",
    "": "未知",
}

ACTION_LABELS: dict[str, str] = {
    "paper_buy": "买入",
    "paper_sell": "卖出",
    "paper_reduce": "减仓",
    "paper_hold": "未交易",
    "paper_watchlist": "未成交",
    "paper_risk_alert": "未成交",
    "buy": "买入",
    "sell": "卖出",
    "reduce": "减仓",
}

ALLOCATION_LABELS: dict[str, str] = {
    "total_asset": "当前总资产",
    "total_assets": "当前总资产",
    "reserved_cash": "保留现金",
    "planned_investable_cash": "计划可投资现金",
    "initial_allocated_cash": "初始已分配资金",
    "released_budget": "释放预算",
    "redistributed_cash": "再分配资金",
    "actual_invested_cash": "实际投入资金",
    "unavoidable_residual_cash": "不可避免剩余现金",
    "capital_utilization_rate": "资金利用率",
    "cash_ratio_after_allocation": "分配后现金比例",
    "maximum_cash_ratio": "最高现金比例",
    "cash_cap_exception": "现金超限例外",
    "cash_cap_exception_reason": "现金超限原因",
}


def display_label(key: Any) -> str:
    text = str(key or "")
    return ACCOUNT_SUMMARY_LABELS.get(text, ALLOCATION_LABELS.get(text, text))


def risk_level_label(value: Any) -> str:
    text = str(value or "unknown").strip()
    return RISK_LEVEL_LABELS.get(text, text)


def action_label(value: Any) -> str:
    text = str(value or "").strip()
    return ACTION_LABELS.get(text, text)
