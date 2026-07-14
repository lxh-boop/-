from pipelines.fixed_top10_inputs import merge_original_ranking_with_ai


def test_ai_does_not_change_top10_membership() -> None:
    original = [
        {"trade_date": "2026-04-01", "stock_code": f"{index:06d}", "rank": index, "pred_score": 1 - index / 100, "close": 10}
        for index in range(1, 13)
    ]
    ai = [
        {
            "trade_date": "2026-04-01",
            "stock_code": f"{index:06d}",
            "final_rank": 1 if index == 12 else index + 20,
            "final_score": 10 if index == 12 else 1 - index / 100,
            "final_action": "keep",
            "target_weight": 0.08,
        }
        for index in range(1, 13)
    ]

    result = merge_original_ranking_with_ai(original, ai, trade_date="2026-04-01")

    assert [row["stock_code"] for row in result.original_top10] == [f"{index:06d}" for index in range(1, 11)]
    assert "000012" not in [row["stock_code"] for row in result.original_top10]
