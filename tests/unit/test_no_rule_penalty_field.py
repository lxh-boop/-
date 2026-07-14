from scoring.final_score import build_final_recommendations


def test_recommendation_has_no_rule_penalty_fields() -> None:
    data = build_final_recommendations(
        [{"trade_date": "2026-06-11", "stock_code": "000001", "pred_score": 0.8, "pred_rank": 1}]
    )[0].to_dict()

    assert "rule_penalty" not in data
    assert "rule_penalty_score" not in data

