"""Portfolio and paper trading foundation."""

from portfolio.paper_account import create_default_account
from portfolio.paper_order import create_paper_order
from portfolio.paper_position import create_position
from portfolio.paper_trading_engine import execute_paper_rebalance, generate_paper_orders
from portfolio.decision_attribution import explain_stock_decision_attribution, render_decision_attribution_markdown
from portfolio.portfolio_risk import calculate_portfolio_risk
from portfolio.rebalance_rules import build_rebalance_plan
from portfolio.schemas import (
    PAPER_TRADING_DISCLAIMER,
    InvestmentGoal,
    PaperAccount,
    PaperOrder,
    PaperPosition,
    PortfolioRiskReport,
    RebalanceDecision,
    RebalancePlan,
    RiskAssessment,
    TradingBehavior,
    UserProfile,
)
from portfolio.storage import PortfolioStorage
from portfolio.user_profile import build_user_constraints, default_user_profile, load_user_context

__all__ = [
    "PAPER_TRADING_DISCLAIMER",
    "UserProfile",
    "RiskAssessment",
    "InvestmentGoal",
    "TradingBehavior",
    "PaperAccount",
    "PaperPosition",
    "PaperOrder",
    "PortfolioRiskReport",
    "RebalanceDecision",
    "RebalancePlan",
    "default_user_profile",
    "build_user_constraints",
    "load_user_context",
    "create_default_account",
    "create_position",
    "create_paper_order",
    "calculate_portfolio_risk",
    "build_rebalance_plan",
    "execute_paper_rebalance",
    "generate_paper_orders",
    "PortfolioStorage",
    "explain_stock_decision_attribution",
    "render_decision_attribution_markdown",
]
