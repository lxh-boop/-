from __future__ import annotations

import pytest

from skills.base import validate_skill_result
from skills.schemas import (
    COMPLIANCE_DISCLAIMER,
    AgentEffectivenessContext,
    EvidenceSnapshot,
    ModelPredictionContext,
    NewsRiskContext,
    SkillRequest,
    SkillResult,
    UserSuitabilityContext,
    clamp_score,
    validate_action,
)


def test_skill_result_normalizes_action_confidence_and_score() -> None:
    result = SkillResult(
        skill_name="signal_fusion",
        action="down_weight",
        score_adjustment=-1.5,
        confidence=1.2,
        reason="negative news risk",
    )

    data = result.to_dict()

    assert data["action"] == "down_weight"
    assert data["score_adjustment"] == -1.0
    assert data["confidence"] == 1.0
    assert data["risk_warning"] == COMPLIANCE_DISCLAIMER


def test_invalid_action_is_rejected() -> None:
    with pytest.raises(ValueError):
        validate_action("buy")

    with pytest.raises(ValueError):
        SkillResult(skill_name="compliance", action="sell").to_dict()


def test_validate_skill_result_checks_confidence_range() -> None:
    with pytest.raises(ValueError):
        validate_skill_result(
            SkillResult(skill_name="news_impact_scoring", action="risk_warning", confidence=1.1)
        )


def test_common_skill_request_contexts_are_composable() -> None:
    user = UserSuitabilityContext(
        user_id="demo_user",
        risk_level="C2",
        liquidity_need="高",
        current_positions=[{"asset_code": "300750", "position_ratio": 0.2}],
    )
    prediction = ModelPredictionContext(
        trade_date="2026-06-11",
        stock_code="300750",
        stock_name="宁德时代",
        model_name="chronos_bolt_small",
        pred_score=0.72,
        pred_rank=10,
        confidence="medium",
    )
    news = NewsRiskContext(
        news_id="news_001",
        trade_date="2026-06-11",
        event_type="监管",
        sentiment="negative",
        impact_direction="negative",
        impact_strength=0.7,
        mapping_confidence=0.85,
        evidence_text="监管处罚风险提示。",
        stock_code="300750",
    )
    evidence = EvidenceSnapshot(
        evidence_id="chunk_001",
        evidence_type="news_chunk",
        source_id="news_001",
        text="监管处罚风险提示。",
    )

    request = SkillRequest(
        skill_name="signal_fusion",
        trade_date="2026-06-11",
        user=user,
        prediction=prediction,
        news_events=[news],
        evidence=[evidence],
    )
    effectiveness = AgentEffectivenessContext(
        decision_id="decision_001",
        trade_date="2026-06-11",
        stock_code="300750",
        original_pred_score=0.72,
        final_action="down_weight",
        final_score=0.58,
    )

    assert request.user.risk_level == "C2"
    assert request.prediction.stock_code == "300750"
    assert request.news_events[0].mapping_confidence == 0.85
    assert effectiveness.final_action == "down_weight"
    assert clamp_score(2.0) == 1.0
