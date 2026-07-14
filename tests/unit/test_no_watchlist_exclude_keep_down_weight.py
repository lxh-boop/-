from scoring.final_score import build_final_recommendations


def test_recommendation_does_not_emit_action_classification_values() -> None:
    records = build_final_recommendations(
        [{"trade_date": "2026-06-11", "stock_code": "000001", "pred_score": 0.8, "pred_rank": 1}],
        ai_reliability_weight=1.0,
    )

    values = {str(value) for value in records[0].to_dict().values()}
    assert not (values & {"hold", "exclude", "keep", "down_weight", "risk_alert"})

