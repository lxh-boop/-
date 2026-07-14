from scoring.final_score import build_final_recommendations


def test_final_recommendation_has_no_final_action_field() -> None:
    records = build_final_recommendations(
        [{"trade_date": "2026-06-11", "stock_code": "000001", "pred_score": 0.8, "pred_rank": 1}],
        ai_reliability_weight=0.0,
    )

    data = records[0].to_dict()
    assert "final_action" not in data
    assert "final_score" not in data

