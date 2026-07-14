from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def _model(risk_level: str = "high") -> ModelPredictionSignal:
    return ModelPredictionSignal(
        trade_date="2026-06-12",
        stock_code="000001",
        stock_name="平安银行",
        pred_score=0.82,
        pred_rank=1,
        confidence="high",
        risk_level=risk_level,
        total_count=100,
    )


def test_ordinary_high_risk_reduces_position_not_exclude() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=_model("high"),
            user_constraints=UserConstraintSignal(user_id="u1", risk_level="C2", profile_type="稳健偏保守"),
            portfolio_constraints=PortfolioConstraintSignal(stock_risk_level="high", confidence="high"),
            ai_reliability_weight=0.70,
        )
    )

    assert not hasattr(output, "final_action")
    assert output.target_weight > 0
    assert output.target_weight < output.original_target_weight
    assert 0 < output.position_adjustment_ratio < 1


def test_c1_user_reduces_more_than_c5_user() -> None:
    conservative = fuse_signal(
        FusionInput(
            model_prediction=_model("high"),
            user_constraints=UserConstraintSignal(user_id="c1", risk_level="C1", profile_type="保守型"),
            portfolio_constraints=PortfolioConstraintSignal(stock_risk_level="high", confidence="high"),
            ai_reliability_weight=0.80,
        )
    )
    aggressive = fuse_signal(
        FusionInput(
            model_prediction=_model("high"),
            user_constraints=UserConstraintSignal(user_id="c5", risk_level="C5", profile_type="激进型", max_single_position=0.15),
            portfolio_constraints=PortfolioConstraintSignal(stock_risk_level="high", confidence="high", max_single_position=0.15),
            ai_reliability_weight=0.80,
        )
    )

    assert not hasattr(conservative, "final_action")
    assert not hasattr(aggressive, "final_action")
    assert conservative.position_adjustment_ratio < aggressive.position_adjustment_ratio
    assert conservative.original_target_weight <= 0.03
    assert aggressive.original_target_weight <= 0.15
