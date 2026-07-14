from __future__ import annotations

from database.repositories import (
    AgentRepository,
    EvaluationRepository,
    NewsRepository,
    PortfolioRepository,
    PredictionRepository,
    StockRepository,
    UserRepository,
)


def test_repositories_insert_get_list_update(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"

    user_repo = UserRepository(db_path)
    user_repo.insert_risk_assessment(
        {
            "assessment_id": "risk_001",
            "user_id": "user_001",
            "risk_score": 42.0,
            "risk_level": "C2",
            "investment_horizon": "短期",
            "is_valid": 1,
        }
    )
    assert user_repo.get_risk_assessment("risk_001")["risk_level"] == "C2"
    user_repo.update_risk_assessment("risk_001", {"risk_level": "C3"})
    assert user_repo.get_risk_assessment("risk_001")["risk_level"] == "C3"

    portfolio_repo = PortfolioRepository(db_path)
    portfolio_repo.insert_position(
        {
            "position_id": "pos_001",
            "user_id": "user_001",
            "asset_code": "300750",
            "asset_name": "宁德时代",
            "asset_type": "股票",
            "position_ratio": 0.2,
            "industry": "动力电池",
        }
    )
    assert len(portfolio_repo.list_positions("user_001")) == 1

    stock_repo = StockRepository(db_path)
    stock_repo.insert_stock_basic(
        {
            "stock_code": "300750",
            "stock_name": "宁德时代",
            "industry": "动力电池",
            "concepts": ["新能源", "动力电池"],
        }
    )
    assert stock_repo.get_stock_basic("300750")["concepts"] == ["新能源", "动力电池"]

    prediction_repo = PredictionRepository(db_path)
    prediction_repo.insert_prediction(
        {
            "prediction_id": "pred_001",
            "trade_date": "2026-06-11",
            "stock_code": "300750",
            "model_name": "chronos_bolt_small",
            "pred_score": 0.8,
            "pred_rank": 10,
            "confidence": "medium",
        }
    )
    assert prediction_repo.get_prediction("pred_001")["stock_code"] == "300750"

    news_repo = NewsRepository(db_path)
    news_repo.insert_news_event(
        {
            "news_id": "news_001",
            "title": "公司公告",
            "summary": "风险提示",
            "source": "交易所",
            "publish_time": "2026-06-11 10:00:00",
            "trade_date": "2026-06-11",
            "event_type": "公告",
            "retention_level": "hot",
        }
    )
    news_repo.insert_news_chunk(
        {
            "chunk_id": "chunk_001",
            "news_id": "news_001",
            "chunk_index": 0,
            "chunk_text": "公告风险提示正文。",
            "trade_date": "2026-06-11",
        }
    )
    assert news_repo.get_news_chunk("chunk_001")["chunk_text"] == "公告风险提示正文。"

    agent_repo = AgentRepository(db_path)
    agent_repo.insert_agent_rule(
        {
            "rule_id": "rule_001",
            "rule_name": "低置信观察",
            "rule_type": "模型可靠性",
            "condition": {"confidence": "low"},
            "action": "watch",
            "priority": 10,
            "is_active": 1,
        }
    )
    assert agent_repo.get_agent_rule("rule_001")["condition"] == {"confidence": "low"}

    eval_repo = EvaluationRepository(db_path)
    eval_repo.insert_backtest_evaluation(
        {
            "eval_id": "eval_001",
            "strategy_name": "agent_overlay",
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "topk": 10,
            "agent_modify_count": 3,
            "useful_modify_count": 2,
        }
    )
    assert eval_repo.get_backtest_evaluation("eval_001")["strategy_name"] == "agent_overlay"
