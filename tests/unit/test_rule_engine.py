from __future__ import annotations

from scoring.news_adjustment import calculate_news_adjustment
from scoring.rule_engine import evaluate_rules
from scoring.schemas import ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal


def test_major_negative_news_forces_risk_alert_or_down_weight() -> None:
    model = ModelPredictionSignal("2026-06-11", "000001", 0.9, confidence="high", risk_level="medium")
    user = UserConstraintSignal(risk_level="C3")
    portfolio = PortfolioConstraintSignal()
    news = calculate_news_adjustment(
        {
            "news_id": "news_001",
            "impact_direction": "negative",
            "impact_strength": 1.0,
            "impact_confidence": 0.9,
            "mapping_confidence": 0.9,
            "publish_time": "2026-06-11 10:00:00",
            "trade_date": "2026-06-11",
        }
    )

    result = evaluate_rules(model, user, portfolio, news)

    assert result.forced_action in {"risk_alert", "down_weight"}
    assert any(rule.rule_id == "major_negative_news" for rule in result.triggered_rules)


def test_low_confidence_prediction_forces_watchlist() -> None:
    model = ModelPredictionSignal("2026-06-11", "000001", 0.9, confidence="low")
    result = evaluate_rules(model, UserConstraintSignal(), PortfolioConstraintSignal(), calculate_news_adjustment(None))

    assert result.forced_action == "hold"
    assert any(rule.rule_id == "low_confidence_prediction" for rule in result.triggered_rules)


def test_st_or_extreme_risk_asset_forces_exclude() -> None:
    model = ModelPredictionSignal("2026-06-11", "000001", 0.9, stock_name="ST Demo", confidence="high")
    result = evaluate_rules(model, UserConstraintSignal(), PortfolioConstraintSignal(), calculate_news_adjustment(None))

    assert result.forced_action == "exclude"
