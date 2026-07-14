from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from scoring.schemas import (
    AgentRuleSignal,
    FinalRecommendationRecord,
    FusionInput,
    ModelPredictionSignal,
    NewsEvidenceSignal,
    PortfolioConstraintSignal,
    UserConstraintSignal,
)
from scoring.signal_fusion import fuse_signal


DEFAULT_RECOMMENDATION_DIR = Path("outputs") / "recommendations"


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _group_news(news_items: list[dict[str, Any] | NewsEvidenceSignal] | None) -> dict[str, list[NewsEvidenceSignal]]:
    grouped: dict[str, list[NewsEvidenceSignal]] = {}
    for item in news_items or []:
        signal = item if isinstance(item, NewsEvidenceSignal) else NewsEvidenceSignal.from_mapping(item)
        grouped.setdefault(_stock_code(signal.stock_code), []).append(signal)
    return grouped


def _portfolio_for_stock(
    stock_code: str,
    portfolio_constraints: dict[str, Any] | PortfolioConstraintSignal | None,
) -> PortfolioConstraintSignal:
    if isinstance(portfolio_constraints, PortfolioConstraintSignal):
        return portfolio_constraints
    if isinstance(portfolio_constraints, dict):
        by_stock = portfolio_constraints.get("by_stock")
        if isinstance(by_stock, dict) and stock_code in by_stock:
            return PortfolioConstraintSignal.from_mapping(by_stock[stock_code])
        return PortfolioConstraintSignal.from_mapping(portfolio_constraints)
    return PortfolioConstraintSignal()


def build_final_recommendations(
    model_predictions: list[dict[str, Any] | ModelPredictionSignal],
    news_stock_mapping: list[dict[str, Any] | NewsEvidenceSignal] | None = None,
    rag_evidence: list[dict[str, Any]] | None = None,
    user_profile: dict[str, Any] | UserConstraintSignal | None = None,
    risk_assessment: dict[str, Any] | None = None,
    investment_goal: dict[str, Any] | None = None,
    portfolio_position: list[dict[str, Any]] | None = None,
    portfolio_risk: dict[str, Any] | PortfolioConstraintSignal | None = None,
    agent_rule: list[dict[str, Any] | AgentRuleSignal] | None = None,
    ai_reliability_weight: float = 0.00,
) -> list[FinalRecommendationRecord]:
    user_data: dict[str, Any] = {}
    if isinstance(user_profile, UserConstraintSignal):
        user_constraints = user_profile
    else:
        user_data.update(user_profile or {})
        user_data.update(risk_assessment or {})
        user_data.update(investment_goal or {})
        user_constraints = UserConstraintSignal.from_mapping(user_data)

    news_by_stock = _group_news(news_stock_mapping)
    rules = [item if isinstance(item, AgentRuleSignal) else AgentRuleSignal.from_mapping(item) for item in (agent_rule or [])]
    total_count = len(model_predictions)
    records: list[FinalRecommendationRecord] = []

    for raw in model_predictions:
        model = raw if isinstance(raw, ModelPredictionSignal) else ModelPredictionSignal.from_mapping(raw)
        if model.total_count is None:
            model = ModelPredictionSignal(
                trade_date=model.trade_date,
                stock_code=model.stock_code,
                stock_name=model.stock_name,
                industry=model.industry,
                pred_score=model.pred_score,
                pred_rank=model.pred_rank,
                confidence=model.confidence,
                model_name=model.model_name,
                pred_return=model.pred_return,
                current_price=model.current_price,
                risk_level=model.risk_level,
                total_count=total_count,
            )
        portfolio = _portfolio_for_stock(model.stock_code, portfolio_risk)
        fusion_output = fuse_signal(
            FusionInput(
                model_prediction=model,
                news_evidence=news_by_stock.get(_stock_code(model.stock_code), []),
                user_constraints=user_constraints,
                portfolio_constraints=portfolio,
                agent_rules=rules,
                rag_evidence=rag_evidence or [],
                ai_reliability_weight=float(ai_reliability_weight),
            )
        )
        records.append(
            FinalRecommendationRecord(
                output=fusion_output,
                stock_name=model.stock_name,
                model_name=model.model_name,
            )
        )
    return records


def save_final_recommendations(
    records: list[FinalRecommendationRecord],
    output_dir: str | Path = DEFAULT_RECOMMENDATION_DIR,
    trade_date: str | None = None,
) -> dict[str, Path]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [record.to_dict() for record in records]
    trade_date = trade_date or (records[0].output.trade_date if records else "unknown")
    date_token = str(trade_date).replace("-", "")
    latest_csv = out_dir / "final_recommendations_latest.csv"
    dated_csv = out_dir / f"final_recommendations_{date_token}.csv"
    latest_json = out_dir / "final_recommendations_latest.json"

    fieldnames = sorted({key for row in rows for key in row})
    for path in [latest_csv, dated_csv]:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
    latest_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"latest_csv": latest_csv, "dated_csv": dated_csv, "latest_json": latest_json}


def generate_final_recommendations(
    model_predictions: list[dict[str, Any] | ModelPredictionSignal],
    output_dir: str | Path = DEFAULT_RECOMMENDATION_DIR,
    save: bool = True,
    **kwargs: Any,
) -> tuple[list[FinalRecommendationRecord], dict[str, Path]]:
    records = build_final_recommendations(model_predictions, **kwargs)
    paths = save_final_recommendations(records, output_dir=output_dir) if save else {}
    return records, paths
