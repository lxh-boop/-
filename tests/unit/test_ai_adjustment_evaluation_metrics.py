from evaluation.adjustment_metrics import calculate_adjustment_metrics


def test_down_weight_avoids_loss_and_scores_hit() -> None:
    metrics = calculate_adjustment_metrics(
        {
            "original_target_weight": 0.10,
            "target_weight": 0.05,
            "future_excess_return_5d": -0.08,
        }
    )

    assert metrics["adjustment_hit"] == 1
    assert metrics["avoided_loss"] > 0
    assert metrics["missed_gain"] == 0
    assert metrics["adjustment_alpha"] > 0
    assert 0 <= metrics["ai_adjustment_score"] <= 1


def test_down_weight_can_miss_gain() -> None:
    metrics = calculate_adjustment_metrics(
        {
            "original_target_weight": 0.10,
            "target_weight": 0.05,
            "future_excess_return_5d": 0.08,
        }
    )

    assert metrics["adjustment_hit"] == 0
    assert metrics["missed_gain"] > 0
    assert metrics["avoided_loss"] == 0
    assert metrics["false_down_weight"] == 1
    assert metrics["adjustment_alpha"] < 0
