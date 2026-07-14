from __future__ import annotations

import sys

from scoring.explain import generate_explanation
from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_scoring_explain_is_structured_and_does_not_require_llm() -> None:
    before_modules = set(sys.modules)
    fusion_input = FusionInput(
        model_prediction=ModelPredictionSignal("2026-06-11", "000001", 0.8, confidence="medium"),
        user_constraints=UserConstraintSignal(user_id="u1"),
        portfolio_constraints=PortfolioConstraintSignal(),
    )
    output = fuse_signal(fusion_input)
    explanation = generate_explanation(output, fusion_input)

    assert "llm_client" not in (set(sys.modules) - before_modules)
    assert explanation["model_signal"]
    assert "news_evidence" in explanation
    assert "user_constraints" in explanation
    assert "portfolio_risk" in explanation
    assert explanation["combined_adjustment"] == output.combined_adjustment
    assert explanation["position_adjustment_ratio"] == output.position_adjustment_ratio
    assert "final_action" not in explanation
    assert explanation["compliance_disclaimer"]
