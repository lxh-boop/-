from evaluation.ai_adjustment_evaluator import evaluate_ai_adjustment_record, evaluate_due_adjustments


def test_missing_future_return_marks_evaluation_pending() -> None:
    row = evaluate_ai_adjustment_record(
        {
            "user_id": "u1",
            "trade_date": "2026-06-12",
            "stock_code": "1",
            "original_target_weight": 0.08,
            "target_weight": 0.04,
        }
    )

    assert row["evaluation_status"] == "pending"
    assert row["stock_code"] == "000001"
    assert row["ai_adjustment_score"] == ""


def test_evaluate_due_adjustments_counts_pending_and_evaluated() -> None:
    result = evaluate_due_adjustments(
        [
            {"user_id": "u1", "trade_date": "2026-06-12", "stock_code": "1", "original_target_weight": 0.08, "target_weight": 0.04},
            {"user_id": "u1", "trade_date": "2026-06-12", "stock_code": "2", "original_target_weight": 0.08, "target_weight": 0.08, "future_return_5d": 0.02},
        ]
    )

    assert result["pending_count"] == 1
    assert result["evaluated_count"] == 1
