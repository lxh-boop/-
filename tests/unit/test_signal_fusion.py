from __future__ import annotations

from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_fusion_output_contains_required_audit_fields() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal(
                "2026-06-11",
                "000001",
                0.95,
                pred_rank=1,
                total_count=10,
                confidence="high",
                industry="bank",
            ),
            news_evidence=[
                {
                    "news_id": "news_001",
                    "stock_code": "000001",
                    "impact_direction": "positive",
                    "impact_strength": 0.8,
                    "impact_confidence": 0.8,
                    "mapping_confidence": 0.8,
                    "evidence_chunk_ids": ["chunk_001"],
                    "publish_time": "2026-06-11 10:00:00",
                    "trade_date": "2026-06-11",
                }
            ],
            user_constraints=UserConstraintSignal(user_id="u1", preferred_industries=["bank"], allow_high_volatility=False),
            portfolio_constraints=PortfolioConstraintSignal(confidence="high", stock_industry="bank"),
        )
    )

    assert not hasattr(output, "final_action")
    assert output.position_adjustment_ratio > 1.0
    assert output.evidence_news_ids == ["news_001"]
    assert output.evidence_chunk_ids == ["chunk_001"]
    assert output.reason
    assert output.compliance_disclaimer


def test_forced_action_has_priority_over_final_score() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal(
                "2026-06-11",
                "000001",
                1.0,
                pred_rank=1,
                total_count=10,
                confidence="high",
                risk_level="high",
            ),
            user_constraints=UserConstraintSignal(user_id="u1", profile_type="conservative", risk_level="C2"),
            portfolio_constraints=PortfolioConstraintSignal(confidence="high", stock_risk_level="high"),
        )
    )

    assert not hasattr(output, "final_action")
    assert output.target_weight > 0
    assert output.target_weight < output.original_target_weight


def test_missing_news_does_not_penalize_news_adjustment() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal("2026-06-11", "000001", 0.8, confidence="medium"),
            user_constraints=UserConstraintSignal(),
            portfolio_constraints=PortfolioConstraintSignal(),
        )
    )

    assert output.news_adjustment == 0
