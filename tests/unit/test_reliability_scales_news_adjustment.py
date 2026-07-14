from scoring.schemas import FusionInput, ModelPredictionSignal
from scoring.signal_fusion import fuse_signal


def test_reliability_scales_only_news_adjustment() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal("2026-06-11", "000001", 0.8, pred_rank=1, total_count=10),
            news_evidence=[
                {
                    "news_id": "n1",
                    "stock_code": "000001",
                    "impact_direction": "positive",
                    "impact_strength": 1.0,
                    "impact_confidence": 1.0,
                    "mapping_confidence": 1.0,
                    "importance_score": 1.0,
                    "publish_time": "2026-06-11 10:00:00",
                    "trade_date": "2026-06-11",
                }
            ],
            ai_reliability_weight=0.5,
        )
    )

    assert output.news_adjustment == 0.30
    assert output.effective_news_adjustment == 0.15
    assert output.combined_adjustment == 0.15
    assert output.position_adjustment_ratio == 1.15

