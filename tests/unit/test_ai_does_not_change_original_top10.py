from pipelines.fixed_top10_inputs import merge_original_ranking_with_ai


def test_ai_numeric_adjustment_does_not_change_original_top10_membership() -> None:
    originals = [
        {"trade_date": "2026-04-01", "stock_code": f"{i:06d}", "pred_score": 1 - i / 100, "rank": i, "current_price": 10}
        for i in range(1, 13)
    ]
    ai_rows = [
        {
            "trade_date": "2026-04-01",
            "stock_code": f"{i:06d}",
            "combined_adjustment": 1.0 if i == 12 else -1.0,
            "position_adjustment_ratio": 2.0 if i == 12 else 0.0,
        }
        for i in range(1, 13)
    ]

    result = merge_original_ranking_with_ai(originals, ai_rows, "2026-04-01", top_n=10)

    assert [row["stock_code"] for row in result.original_top10] == [f"{i:06d}" for i in range(1, 11)]

