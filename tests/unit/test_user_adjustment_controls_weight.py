from scoring.schemas import FusionInput, ModelPredictionSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_user_adjustment_controls_position_ratio_without_ai_reliability_scaling() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal(
                "2026-06-11",
                "000001",
                0.8,
                pred_rank=1,
                total_count=10,
                risk_level="high",
            ),
            user_constraints=UserConstraintSignal(user_id="u1", profile_type="conservative", risk_level="C2"),
            ai_reliability_weight=0.0,
        )
    )

    assert output.user_adjustment == -0.25
    assert output.effective_news_adjustment == 0.0
    assert output.position_adjustment_ratio == 0.75

