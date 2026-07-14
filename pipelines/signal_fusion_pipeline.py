from __future__ import annotations

from pathlib import Path
from typing import Any

from database.repositories import AgentRepository, NewsRepository, PortfolioRepository, UserRepository
from config import COLD_START_NEWS_RELIABILITY_WEIGHT, ENABLE_COLD_START_NEWS_ADJUSTMENT
from evaluation.evaluation_store import load_ai_reliability_state
from evaluation.reliability_updater import DEFAULT_AI_RELIABILITY_WEIGHT
from pipelines.replay_normalization import normalize_trade_date_text
from pipelines.schemas import PipelineContext, PipelineStatus, SignalFusionPipelineResult
from scoring.decision_logger import log_fusion_output
from scoring.final_score import build_final_recommendations, save_final_recommendations
from scoring.schemas import AgentRuleSignal, ModelPredictionSignal, NewsEvidenceSignal, PortfolioConstraintSignal, UserConstraintSignal


def _latest(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[-1] if rows else None


def _safe_trade_date(value: Any) -> str:
    try:
        return normalize_trade_date_text(value)
    except Exception:
        return ""


def _load_user_constraints(context: PipelineContext) -> UserConstraintSignal:
    try:
        repo = UserRepository(context.db_path)
        profile = repo.get_user_profile(context.user_id) or {"user_id": context.user_id}
        risk = _latest(repo.list_risk_assessments(context.user_id)) or {}
        goal = _latest(repo.list_investment_goals(context.user_id)) or {}
        data = {**profile, **risk, **goal, "user_id": context.user_id}
        return UserConstraintSignal.from_mapping(data)
    except Exception:
        return UserConstraintSignal(user_id=context.user_id)


def _load_agent_rules(context: PipelineContext) -> list[AgentRuleSignal]:
    try:
        rows = AgentRepository(context.db_path).list_agent_rules(active_only=True)
        return [AgentRuleSignal.from_mapping(row) for row in rows]
    except Exception:
        return []


def _load_news_mappings(context: PipelineContext, predictions: list[ModelPredictionSignal]) -> list[NewsEvidenceSignal]:
    try:
        repo = NewsRepository(context.db_path)
        rows = []
        for prediction in predictions:
            prediction_trade_date = _safe_trade_date(prediction.trade_date or context.trade_date)
            for mapping in repo.list_news_stock_mappings(stock_code=prediction.stock_code):
                event = repo.get_news_event(str(mapping.get("news_id") or "")) or {}
                event_trade_date = _safe_trade_date(event.get("trade_date") or mapping.get("trade_date"))
                if prediction_trade_date and event_trade_date and event_trade_date > prediction_trade_date:
                    continue
                row = {
                    **mapping,
                    "publish_time": event.get("publish_time") or mapping.get("publish_time") or "",
                    "trade_date": event.get("trade_date") or mapping.get("trade_date") or "",
                    "importance_score": event.get("importance_score") if event.get("importance_score") not in [None, ""] else mapping.get("importance_score", 1.0),
                    "reason": event.get("title") or mapping.get("evidence_text") or "",
                }
                rows.append(row)
        return [NewsEvidenceSignal.from_mapping(row) for row in rows]
    except Exception:
        return []


def _portfolio_constraints(context: PipelineContext, predictions: list[ModelPredictionSignal]) -> dict[str, Any]:
    by_stock: dict[str, dict[str, Any]] = {}
    try:
        positions = PortfolioRepository(context.db_path).list_positions(context.user_id)
    except Exception:
        positions = []
    industry_ratio: dict[str, float] = {}
    for row in positions:
        industry = str(row.get("industry") or "")
        ratio = float(row.get("position_ratio") or 0.0)
        if industry:
            industry_ratio[industry] = industry_ratio.get(industry, 0.0) + ratio
    for prediction in predictions:
        code = prediction.stock_code
        current = next((row for row in positions if str(row.get("asset_code") or "").split(".")[0].zfill(6) == code), None)
        by_stock[code] = {
            "current_position_ratio": float((current or {}).get("position_ratio") or 0.0),
            "industry_position_ratio": industry_ratio.get(prediction.industry, 0.0),
            "stock_risk_level": prediction.risk_level,
            "stock_industry": prediction.industry,
            "confidence": prediction.confidence,
        }
    return {"by_stock": by_stock}


def run_signal_fusion_pipeline(
    context: PipelineContext,
    predictions: list[ModelPredictionSignal],
    rag_evidence: list[NewsEvidenceSignal] | None = None,
    output_dir: str | Path | None = None,
) -> SignalFusionPipelineResult:
    if not predictions:
        return SignalFusionPipelineResult(
            status=PipelineStatus.SKIPPED,
            message="No predictions supplied to signal fusion pipeline.",
            input_count=0,
            output_count=0,
        )

    output_dir = Path(output_dir) if output_dir else context.resolved_output_dir() / "recommendations"
    user_constraints = _load_user_constraints(context)
    news = list(rag_evidence or []) + _load_news_mappings(context, predictions)
    rules = _load_agent_rules(context)
    portfolio = _portfolio_constraints(context, predictions)
    reliability_state = load_ai_reliability_state(context.user_id, context.resolved_output_dir())
    ai_reliability_weight = float(reliability_state.get("ai_reliability_weight") or DEFAULT_AI_RELIABILITY_WEIGHT)
    if ENABLE_COLD_START_NEWS_ADJUSTMENT and str(reliability_state.get("status") or "") == "cold_start" and ai_reliability_weight <= 0:
        ai_reliability_weight = float(COLD_START_NEWS_RELIABILITY_WEIGHT)
    records = build_final_recommendations(
        predictions,
        news_stock_mapping=news,
        user_profile=user_constraints,
        portfolio_risk=portfolio,
        agent_rule=rules,
        ai_reliability_weight=ai_reliability_weight,
    )

    paths = {} if context.dry_run else save_final_recommendations(records, output_dir=output_dir)
    decision_log_count = 0
    warnings: list[str] = []
    if not context.dry_run:
        for record in records:
            try:
                log_fusion_output(
                    record.output,
                    db_path=context.db_path,
                    evidence_snapshot=[
                        item.to_dict() if hasattr(item, "to_dict") else dict(item)
                        for item in news
                        if getattr(item, "stock_code", "") == record.output.stock_code
                    ],
                )
                decision_log_count += 1
            except Exception as exc:
                warnings.append(f"failed to write agent_decision_log for {record.output.stock_code}: {exc}")

    return SignalFusionPipelineResult(
        status=PipelineStatus.SUCCESS,
        message=f"Generated {len(records)} final recommendations.",
        input_count=len(predictions),
        output_count=len(records),
        output_paths={key: str(value) for key, value in paths.items()},
        warnings=warnings,
        recommendations=records,
        fusion_outputs=[record.output for record in records],
        decision_log_count=decision_log_count,
    )
