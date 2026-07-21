from top_k_test_helpers import ranking_result


def test_top_k_insufficient_data(tmp_path) -> None:
    result = ranking_result(tmp_path, requested=10, available=2)

    assert result["summary"]["top_k"] == 10
    assert result["returned_count"] == 2
