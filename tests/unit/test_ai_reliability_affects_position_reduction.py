from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def _input(weight: float) -> FusionInput:
    return FusionInput(
        model_prediction=ModelPredictionSignal(
            trade_date="2026-06-12",
            stock_code="000001",
            pred_score=0.82,
            pred_rank=1,
            confidence="high",
            risk_level="high",
            total_count=100,
        ),
        user_constraints=UserConstraintSignal(user_id="u1", risk_level="C3", profile_type="稳健型"),
        portfolio_constraints=PortfolioConstraintSignal(stock_risk_level="high", confidence="high"),
        ai_reliability_weight=weight,
    )


def test_lower_reliability_makes_down_weight_gentler() -> None:
    high_reliability = fuse_signal(_input(1.00))
    low_reliability = fuse_signal(_input(0.30))

    assert not hasattr(high_reliability, "final_action")
    assert not hasattr(low_reliability, "final_action")
    assert high_reliability.news_adjustment == 0
    assert low_reliability.news_adjustment == 0
    assert high_reliability.target_weight == low_reliability.target_weight
    assert high_reliability.position_adjustment_ratio == low_reliability.position_adjustment_ratio
