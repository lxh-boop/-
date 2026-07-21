from top_k_test_helpers import ranking_result


def test_top_k_returned_count_not_exceed_requested(tmp_path) -> None:
    result = ranking_result(tmp_path, requested=10, available=60)

    assert result["returned_count"] <= result["summary"]["top_k"]
