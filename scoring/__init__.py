"""Signal Fusion Foundation."""

from scoring.decision_logger import build_decision_log_record, log_fusion_output
from scoring.explain import generate_explanation
from scoring.final_score import build_final_recommendations, generate_final_recommendations, save_final_recommendations
from scoring.news_adjustment import calculate_news_adjustment
from scoring.normalizers import clamp, normalize_confidence, normalize_rank, normalize_score, safe_float
from scoring.schemas import (
    COMPLIANCE_DISCLAIMER,
    AgentRuleSignal,
    FinalRecommendationRecord,
    FusionInput,
    FusionOutput,
    ModelPredictionSignal,
    NewsEvidenceSignal,
    PortfolioConstraintSignal,
    ScoreBreakdown,
    TriggeredRule,
    UserConstraintSignal,
)
from scoring.signal_fusion import fuse_signal
from scoring.user_adjustment import calculate_user_adjustment

__all__ = [
    "COMPLIANCE_DISCLAIMER",
    "ModelPredictionSignal",
    "NewsEvidenceSignal",
    "UserConstraintSignal",
    "PortfolioConstraintSignal",
    "AgentRuleSignal",
    "FusionInput",
    "FusionOutput",
    "ScoreBreakdown",
    "TriggeredRule",
    "FinalRecommendationRecord",
    "safe_float",
    "clamp",
    "normalize_score",
    "normalize_rank",
    "normalize_confidence",
    "calculate_news_adjustment",
    "calculate_user_adjustment",
    "fuse_signal",
    "build_final_recommendations",
    "save_final_recommendations",
    "generate_final_recommendations",
    "build_decision_log_record",
    "log_fusion_output",
    "generate_explanation",
]
