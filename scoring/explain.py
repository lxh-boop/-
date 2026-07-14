from __future__ import annotations

from typing import Any

from scoring.schemas import FusionInput, FusionOutput


def generate_explanation(output: FusionOutput, fusion_input: FusionInput | None = None) -> dict[str, Any]:
    model_signal = {
        "original_pred_score": output.original_pred_score,
        "original_pred_rank": output.original_pred_rank,
        "confidence": output.confidence,
    }
    if fusion_input:
        model_signal.update(fusion_input.model_prediction.to_dict())

    explanation = {
        "model_signal": model_signal,
        "news_evidence": {
            "news_adjustment": output.news_adjustment,
            "effective_news_adjustment": output.effective_news_adjustment,
            "evidence_news_ids": output.evidence_news_ids,
            "evidence_chunk_ids": output.evidence_chunk_ids,
        },
        "user_constraints": fusion_input.user_constraints.to_dict() if fusion_input and fusion_input.user_constraints else {},
        "portfolio_risk": fusion_input.portfolio_constraints.to_dict() if fusion_input and fusion_input.portfolio_constraints else {},
        "user_adjustment": output.user_adjustment,
        "combined_adjustment": output.combined_adjustment,
        "position_adjustment_ratio": output.position_adjustment_ratio,
        "target_weight": output.target_weight,
        "compliance_disclaimer": output.compliance_disclaimer,
    }
    explanation["explanation_text"] = (
        f"Model signal score={output.original_pred_score:.3f}, rank={output.original_pred_rank}. "
        f"News adjustment={output.news_adjustment:.3f}; "
        f"effective news adjustment={output.effective_news_adjustment:.3f}; "
        f"user adjustment={output.user_adjustment:.3f}; "
        f"combined adjustment={output.combined_adjustment:.3f}; "
        f"position ratio={output.position_adjustment_ratio:.3f}. "
        f"{output.compliance_disclaimer}"
    )
    return explanation
