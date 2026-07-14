from scoring.schemas import FusionInput, ModelPredictionSignal
from scoring.signal_fusion import fuse_signal


def test_position_ratio_uses_numeric_adjustments_without_action_label() -> None:
    output = fuse_signal(
        FusionInput(
            model_prediction=ModelPredictionSignal("2026-06-11", "000001", 0.8, pred_rank=1, total_count=10),
            ai_reliability_weight=0.0,
        )
    )

    data = output.to_dict()
    assert data["position_adjustment_ratio"] == 1.0
    assert "final_action" not in data

