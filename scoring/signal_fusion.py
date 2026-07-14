from __future__ import annotations

from typing import Any

from scoring.news_adjustment import calculate_news_adjustment
from scoring.normalizers import clamp, normalize_confidence, normalize_rank, normalize_score
from scoring.schemas import (
    FusionInput,
    FusionOutput,
    ModelPredictionSignal,
    PortfolioConstraintSignal,
    ScoreBreakdown,
    UserConstraintSignal,
)
from scoring.user_adjustment import calculate_user_adjustment


AI_RELIABILITY_MIN = 0.0
AI_RELIABILITY_MAX = 1.0
MIN_POSITION_ADJUSTMENT_RATIO = 0.0
MAX_POSITION_ADJUSTMENT_RATIO = 2.0


def _original_target_weight(user: UserConstraintSignal, portfolio: PortfolioConstraintSignal, cap: float) -> float:
    return max(0.0, min(cap, user.max_single_position, portfolio.max_single_position))


def _target_weight_details(original_target_weight: float, position_adjustment_ratio: float) -> tuple[float, str]:
    original = max(0.0, float(original_target_weight))
    if original <= 0:
        return 0.0, "No original target weight is available."
    return original * position_adjustment_ratio, "Position ratio comes only from news adjustment, user suitability, and AI reliability."


def _model_score_norm(model: ModelPredictionSignal) -> float:
    raw = normalize_score(model.pred_score, 0.0, 1.0)
    if model.pred_rank is not None and model.total_count:
        return 0.70 * raw + 0.30 * normalize_rank(model.pred_rank, model.total_count)
    return raw


def fuse_signal(fusion_input: FusionInput | dict[str, Any]) -> FusionOutput:
    if isinstance(fusion_input, dict):
        model = fusion_input["model_prediction"]
        model_signal = model if isinstance(model, ModelPredictionSignal) else ModelPredictionSignal.from_mapping(model)
        user = UserConstraintSignal.from_mapping(fusion_input.get("user_constraints"))
        portfolio = PortfolioConstraintSignal.from_mapping(fusion_input.get("portfolio_constraints"))
        news_evidence = fusion_input.get("news_evidence") or []
        agent_rules = fusion_input.get("agent_rules") or []
        fusion_input = FusionInput(
            model_prediction=model_signal,
            news_evidence=news_evidence,
            user_constraints=user,
            portfolio_constraints=portfolio,
            agent_rules=agent_rules,
            rag_evidence=fusion_input.get("rag_evidence") or [],
            ai_reliability_weight=float(fusion_input.get("ai_reliability_weight") or 0.0),
        )

    model = fusion_input.model_prediction
    user = fusion_input.user_constraints or UserConstraintSignal()
    portfolio = fusion_input.portfolio_constraints or PortfolioConstraintSignal(
        max_single_position=user.max_single_position,
        max_industry_position=user.max_industry_position,
        stock_risk_level=model.risk_level,
        confidence=model.confidence,
    )

    news = calculate_news_adjustment(fusion_input.news_evidence, trade_date=model.trade_date)
    stock_industry = model.industry or portfolio.stock_industry
    user_adjustment = calculate_user_adjustment(
        user,
        stock_risk_level=model.risk_level,
        stock_industry=stock_industry,
        volatility=portfolio.volatility,
    )
    ai_reliability_weight = clamp(float(fusion_input.ai_reliability_weight), AI_RELIABILITY_MIN, AI_RELIABILITY_MAX)

    model_norm = _model_score_norm(model)
    confidence_score = normalize_confidence(model.confidence)
    news_adjustment = float(news.news_adjustment_score)
    user_adjustment_score = float(user_adjustment.user_adjustment_score)
    effective_news_adjustment = ai_reliability_weight * news_adjustment
    combined_adjustment = effective_news_adjustment + user_adjustment_score
    position_adjustment_ratio = clamp(
        1.0 + combined_adjustment,
        MIN_POSITION_ADJUSTMENT_RATIO,
        MAX_POSITION_ADJUSTMENT_RATIO,
    )
    original_target_weight = _original_target_weight(user, portfolio, user_adjustment.target_weight_cap)
    target_weight, adjustment_reason = _target_weight_details(original_target_weight, position_adjustment_ratio)
    ai_adjustment_confidence = clamp(0.50 * ai_reliability_weight + 0.50 * confidence_score, 0.0, 1.0)

    reason_parts = [
        f"Model score normalized to {model_norm:.3f}.",
        news.reason,
        user_adjustment.reason,
        f"effective_news_adjustment={effective_news_adjustment:.3f} from ai_reliability_weight={ai_reliability_weight:.3f} * news_adjustment={news_adjustment:.3f}.",
        f"combined_adjustment={combined_adjustment:.3f}; position_adjustment_ratio={position_adjustment_ratio:.3f}.",
        adjustment_reason,
    ]

    breakdown = ScoreBreakdown(
        model_score_norm=model_norm,
        news_adjustment=news_adjustment,
        user_adjustment=user_adjustment_score,
        effective_news_adjustment=effective_news_adjustment,
        combined_adjustment=combined_adjustment,
        confidence_score=confidence_score,
    )
    return FusionOutput(
        user_id=user.user_id,
        trade_date=model.trade_date,
        stock_code=model.stock_code,
        original_pred_score=model.pred_score,
        original_pred_rank=model.pred_rank,
        original_score=model.pred_score,
        original_rank=model.pred_rank,
        news_adjustment=news_adjustment,
        user_adjustment=user_adjustment_score,
        effective_news_adjustment=effective_news_adjustment,
        combined_adjustment=combined_adjustment,
        original_target_weight=original_target_weight,
        target_weight=target_weight,
        position_adjustment_ratio=position_adjustment_ratio,
        adjustment_reason=adjustment_reason,
        ai_adjustment_confidence=ai_adjustment_confidence,
        ai_reliability_weight=ai_reliability_weight,
        ai_adjustment_effect_status="pending",
        ai_adjustment_score=None,
        current_price=model.current_price,
        confidence=str(model.confidence),
        triggered_rules=[],
        evidence_news_ids=news.evidence_news_ids,
        evidence_chunk_ids=news.evidence_chunk_ids,
        reason=" ".join(reason_parts),
        risk_warning="",
        score_breakdown=breakdown,
    )
