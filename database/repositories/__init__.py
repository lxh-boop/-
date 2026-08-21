"""Repository layer for the SQLite financial agent database."""

from database.repositories.agent_repository import AgentRepository
from database.repositories.evaluation_repository import EvaluationRepository
from database.repositories.news_repository import NewsRepository, assign_news_trade_date
from database.repositories.portfolio_repository import PortfolioRepository
from database.repositories.proposal_repository import ProposalRepository
from database.repositories.prediction_repository import (
    PredictionRepository,
    RecommendationRepository,
    RuntimeDataImportAuditRepository,
)
from database.repositories.stock_repository import StockRepository
from database.repositories.runtime_state_repository import RuntimeStateRepository
from database.repositories.system_monitor_repository import SystemMonitorRepository
from database.repositories.strategy_workflow_repository import StrategyWorkflowRepository
from database.repositories.user_repository import UserRepository

__all__ = [
    "AgentRepository",
    "EvaluationRepository",
    "NewsRepository",
    "PortfolioRepository",
    "ProposalRepository",
    "PredictionRepository",
    "RecommendationRepository",
    "RuntimeDataImportAuditRepository",
    "RuntimeStateRepository",
    "StockRepository",
    "SystemMonitorRepository",
    "StrategyWorkflowRepository",
    "UserRepository",
    "assign_news_trade_date",
]
