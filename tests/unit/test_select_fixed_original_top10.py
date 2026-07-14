from pipelines.fixed_top10_inputs import select_fixed_original_top10


def test_select_fixed_original_top10_uses_original_rank_score_and_code() -> None:
    rows = [
        {"stock_code": f"{index:06d}", "original_rank": index, "original_score": 1 - index / 100}
        for index in range(12, 0, -1)
    ]

    selected = select_fixed_original_top10(rows)

    assert [row["stock_code"] for row in selected] == [f"{index:06d}" for index in range(1, 11)]
