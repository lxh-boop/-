from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.event_impact_agent import EventImpactAgent
from agent.model_monitor_agent import ModelMonitorAgent
from agent.portfolio_qa_agent import PortfolioQAAgent
from agent.portfolio_review_agent import PortfolioReviewAgent


def get_agent_registry() -> dict[str, Any]:
    return {
        "portfolio_qa": PortfolioQAAgent(),
        "event_impact": EventImpactAgent(),
        "portfolio_review": PortfolioReviewAgent(),
        "model_monitor": ModelMonitorAgent(),
    }


def route_agent(query: str) -> str:
    text = str(query or "").lower()
    event_keywords = ["news", "event", "impact", "affect", "risk event", "新闻", "事件", "影响"]
    review_keywords = ["portfolio review", "review portfolio", "concentration", "loss", "drawdown", "组合复盘", "集中度", "亏损"]
    model_keywords = ["model", "pipeline", "failure", "monitor", "anomaly", "模型", "流水线", "异常", "失败"]
    if any(keyword in text for keyword in event_keywords):
        return "event_impact"
    if any(keyword in text for keyword in review_keywords):
        return "portfolio_review"
    if any(keyword in text for keyword in model_keywords):
        return "model_monitor"
    return "portfolio_qa"


def answer_with_registry(
    query: str,
    user_id: str = "default",
    trade_date: str | None = None,
    stock_code: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    registry = get_agent_registry()
    agent_name = route_agent(query)
    agent = registry[agent_name]
    return agent.answer(
        query=query,
        user_id=user_id,
        trade_date=trade_date,
        stock_code=stock_code,
        output_dir=output_dir,
        db_path=db_path,
        top_k=top_k,
    )
