from top_k_test_helpers import ranking_result


def test_top_k_two_reads_two(tmp_path) -> None:
    result = ranking_result(tmp_path, requested=2)

    assert result["summary"]["source_read_limit"] == 2
    assert result["returned_count"] == 2
