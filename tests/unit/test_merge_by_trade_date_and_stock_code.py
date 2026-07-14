from pipelines.fixed_top10_inputs import merge_original_ranking_with_ai


def test_merge_by_trade_date_and_stock_code_not_row_order() -> None:
    original = [
        {"trade_date": "2026-04-01", "stock_code": "000001", "rank": 1, "pred_score": 0.9, "close": 10},
        {"trade_date": "2026-04-01", "stock_code": "000002", "rank": 2, "pred_score": 0.8, "close": 20},
    ]
    ai = [
        {"trade_date": "2026-04-01", "stock_code": "000002", "final_score": 0.2, "final_action": "down_weight", "target_weight": 0.03},
        {"trade_date": "2026-04-01", "stock_code": "000001", "final_score": 0.7, "final_action": "keep", "target_weight": 0.10},
    ]

    result = merge_original_ranking_with_ai(original, ai, trade_date="2026-04-01", top_n=2)

    by_code = {row["stock_code"]: row for row in result.original_top10}
    assert by_code["000001"]["final_action"] == "keep"
    assert by_code["000002"]["final_action"] == "down_weight"
    assert result.missing_ai_stock_codes == []
