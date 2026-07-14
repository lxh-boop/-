from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_keep_target_weight_is_nonzero() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal("2026-06-12", "000001", 0.9, confidence="high", current_price=10),
            user_constraints=UserConstraintSignal(user_id="u1", risk_level="C3"),
            portfolio_constraints=PortfolioConstraintSignal(confidence="high"),
            ai_reliability_weight=0.0,
        )
    )

    assert not hasattr(output, "final_action")
    assert output.position_adjustment_ratio == 1
    assert output.original_target_weight > 0
    assert output.target_weight > 0


def test_down_weight_target_weight_is_not_zero() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal("2026-06-12", "000001", 0.7, confidence="high", risk_level="high", current_price=10),
            user_constraints=UserConstraintSignal(user_id="u1", risk_level="C3"),
            portfolio_constraints=PortfolioConstraintSignal(confidence="high", stock_risk_level="high"),
            ai_reliability_weight=0.8,
        )
    )

    assert not hasattr(output, "final_action")
    assert output.target_weight > 0
    assert output.position_adjustment_ratio > 0
