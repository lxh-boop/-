from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


PAPER_TRADING_DISCLAIMER = (
    "本模块仅用于 paper trading 模拟盘、机器学习研究和量化策略验证。"
    "不构成投资建议，不用于真实交易，不连接真实券商。"
)


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    profile_type: str = "稳健型"
    age_range: str = ""
    income_level: str = ""
    available_capital: float = 100000.0
    investment_experience: str = "1-3年"
    liquidity_need: str = "中"
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RiskAssessment:
    assessment_id: str
    user_id: str
    risk_score: float
    risk_level: str
    max_drawdown_tolerance: float
    single_loss_tolerance: float = 0.05
    volatility_tolerance: str = "中"
    investment_horizon: str = "中期"
    questionnaire_version: str = "default_v1"
    assessment_time: str = field(default_factory=now_text)
    is_valid: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_valid"] = int(self.is_valid)
        return data


@dataclass(frozen=True)
class InvestmentGoal:
    goal_id: str
    user_id: str
    goal_type: str = "稳健增值"
    target_return: float = 0.06
    target_period: str = "中期"
    priority: str = "风险优先"
    capital_usage: str = "闲置资金"
    created_at: str = field(default_factory=now_text)
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradingBehavior:
    behavior_id: str
    user_id: str
    avg_holding_days: float = 30.0
    turnover_rate: float = 0.2
    avg_position_size: float = 0.08
    preferred_industries: list[str] = field(default_factory=list)
    stop_loss_behavior: str = "unknown"
    max_historical_loss: float = 0.0
    trading_style: str = "中线"
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperAccount:
    account_id: str
    user_id: str
    initial_cash: float = 100000.0
    cash: float = 100000.0
    total_assets: float = 100000.0
    daily_return: float = 0.0
    cumulative_return: float = 0.0
    max_drawdown: float = 0.0
    cumulative_deposit: float = 0.0
    cumulative_withdrawal: float = 0.0
    net_contribution: float = 100000.0
    absolute_profit: float = 0.0
    time_weighted_return: float = 0.0
    daily_fee: float = 0.0
    cumulative_fee: float = 0.0
    position_market_value: float = 0.0
    composite_nav: float = 1.0
    nav: float = 1.0
    drawdown: float = 0.0
    is_paper_trading: bool = True
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_paper_trading"] = int(self.is_paper_trading)
        data.pop("final_score", None)
        return data


@dataclass(frozen=True)
class PaperCashFlow:
    cash_flow_id: str
    user_id: str
    effective_date: str
    flow_type: str
    amount: float
    reason: str = ""
    status: str = "pending"
    source: str = "app"
    run_id: str = ""
    idempotency_key: str = ""
    created_at: str = field(default_factory=now_text)
    applied_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperPosition:
    position_id: str
    user_id: str
    stock_code: str
    stock_name: str = ""
    quantity: float = 0.0
    cost_price: float = 0.0
    current_price: float = 0.0
    market_value: float = 0.0
    position_ratio: float = 0.0
    industry: str = ""
    unrealized_pnl: float = 0.0
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_database_record(self) -> dict[str, Any]:
        return {
            "position_id": self.position_id,
            "user_id": self.user_id,
            "asset_code": self.stock_code,
            "asset_name": self.stock_name,
            "asset_type": "股票",
            "quantity": self.quantity,
            "cost_price": self.cost_price,
            "current_price": self.current_price,
            "market_value": self.market_value,
            "profit_loss": self.unrealized_pnl,
            "position_ratio": self.position_ratio,
            "industry": self.industry,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    user_id: str
    trade_date: str
    stock_code: str
    action: str
    target_weight: float
    executed_price: float
    quantity: float
    reason: str
    stock_name: str = ""
    account_id: str = ""
    decision_id: str = ""
    decision_time: str = ""
    paper_action: str = ""
    current_weight: float = 0.0
    order_amount: float = 0.0
    gross_amount: float = 0.0
    commission_fee: float = 0.0
    other_fee: float = 0.0
    slippage_cost: float = 0.0
    total_fee: float = 0.0
    net_cash_change: float = 0.0
    applied_buy_cost_rate: float = 0.0
    applied_sell_cost_rate: float = 0.0
    risk_warning: str = ""
    triggered_rules: str = ""
    job_id: str = ""
    run_id: str = ""
    execution_source: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    binding_id: str = ""
    config_hash: str = ""
    resolved_config: dict[str, Any] = field(default_factory=dict)
    is_paper_trading: bool = True
    created_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["is_paper_trading"] = int(self.is_paper_trading)
        data.pop("final_score", None)
        data.pop("final_action", None)
        return data


@dataclass(frozen=True)
class PortfolioRiskReport:
    user_id: str
    total_assets: float
    cash_ratio: float
    max_single_position: float
    industry_concentration: dict[str, float]
    max_drawdown: float
    holding_count: int
    high_risk_position_ratio: float
    user_risk_match: bool
    risk_level: str
    risk_warnings: list[str] = field(default_factory=list)
    is_paper_trading: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RebalanceDecision:
    stock_code: str
    stock_name: str
    action: str
    target_weight: float
    reason: str
    risk_warning: str = ""
    industry: str = ""
    final_score: float = 0.0
    risk_level: str = "medium"
    current_price: float = 0.0
    executable_quantity: float = 0.0
    executable_target_amount: float = 0.0
    cannot_execute_reason: str = ""
    source_decision_id: str = ""
    current_weight: float = 0.0
    triggered_rules: str = ""
    original_rank: int = 0
    original_score: float = 0.0
    news_adjustment: float = 0.0
    user_adjustment: float = 0.0
    effective_news_adjustment: float = 0.0
    combined_adjustment: float = 0.0
    position_adjustment_ratio: float = 1.0
    is_paper_trading: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("final_score", None)
        return data


@dataclass(frozen=True)
class RebalancePlan:
    user_id: str
    trade_date: str
    decisions: list[RebalanceDecision]
    total_target_weight: float
    risk_warnings: list[str] = field(default_factory=list)
    execution_diagnostics: dict[str, Any] = field(default_factory=dict)
    job_id: str = ""
    run_id: str = ""
    execution_source: str = ""
    strategy_id: str = ""
    strategy_version: str = ""
    binding_id: str = ""
    config_hash: str = ""
    resolved_config: dict[str, Any] = field(default_factory=dict)
    is_paper_trading: bool = True
    disclaimer: str = PAPER_TRADING_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decisions"] = [decision.to_dict() for decision in self.decisions]
        return data


@dataclass(frozen=True)
class PaperTradingSettings:
    settings_id: str
    user_id: str
    entry_top_k: int = 10
    hold_buffer_rank: int = 15
    max_positions: int = 10
    minimum_cash_ratio: float = 0.05
    target_cash_ratio: float = 0.05
    maximum_cash_ratio: float = 0.30
    min_rebalance_weight_delta: float = 0.01
    strategy_mode: str = "hierarchical_top10"
    buy_cost_rate: float = 0.0003
    sell_cost_rate: float = 0.0008
    minimum_fee: float = 0.0
    slippage_rate: float = 0.0
    execution_price_type: str = "close"
    effective_date: str = ""
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PaperNavRecord:
    nav_id: str
    user_id: str
    account_id: str
    trade_date: str
    cash: float = 0.0
    position_market_value: float = 0.0
    total_assets: float = 0.0
    net_contribution: float = 0.0
    daily_deposit: float = 0.0
    daily_withdrawal: float = 0.0
    daily_fee: float = 0.0
    cumulative_fee: float = 0.0
    daily_profit: float = 0.0
    daily_return: float = 0.0
    cumulative_return: float = 0.0
    time_weighted_return: float = 0.0
    composite_nav: float = 1.0
    nav: float = 1.0
    nav_peak: float = 1.0
    drawdown: float = 0.0
    position_count: int = 0
    updated_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
