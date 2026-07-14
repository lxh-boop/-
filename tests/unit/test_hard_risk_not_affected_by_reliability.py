from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def _hard_input(weight: float) -> FusionInput:
    return FusionInput(
        model_prediction=ModelPredictionSignal(
            trade_date="2026-06-12",
            stock_code="000001",
            stock_name="ST风险股",
            pred_score=0.90,
            pred_rank=1,
            confidence="high",
            risk_level="high",
            total_count=100,
        ),
        user_constraints=UserConstraintSignal(user_id="u1", risk_level="C5", profile_type="激进型"),
        portfolio_constraints=PortfolioConstraintSignal(stock_risk_level="high", confidence="high"),
        ai_reliability_weight=weight,
    )


def test_hard_risk_exclude_ignores_reliability_weight() -> None:
    low = fuse_signal(_hard_input(0.30))
    high = fuse_signal(_hard_input(1.00))

    assert not hasattr(low, "final_action")
    assert not hasattr(high, "final_action")
    assert low.news_adjustment == 0
    assert high.news_adjustment == 0
    assert low.position_adjustment_ratio == high.position_adjustment_ratio
    assert low.target_weight == high.target_weight
