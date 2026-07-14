from scoring.schemas import FusionInput, ModelPredictionSignal, PortfolioConstraintSignal, UserConstraintSignal
from scoring.signal_fusion import fuse_signal


def test_no_negative_news_high_score_keeps_signal() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal(
                trade_date="2026-06-12",
                stock_code="000001",
                pred_score=0.66,
                pred_rank=20,
                total_count=300,
                confidence="medium",
                risk_level="medium",
                current_price=10,
            ),
            user_constraints=UserConstraintSignal(user_id="u1", risk_level="C3"),
            portfolio_constraints=PortfolioConstraintSignal(confidence="medium", stock_risk_level="medium"),
            ai_reliability_weight=0.0,
        )
    )

    assert output.news_adjustment == 0
    assert not hasattr(output, "final_action")
    assert output.position_adjustment_ratio == 1
    assert output.target_weight > 0
