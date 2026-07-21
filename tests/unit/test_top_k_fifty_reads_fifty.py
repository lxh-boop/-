from top_k_test_helpers import ranking_result


def test_top_k_fifty_reads_fifty(tmp_path) -> None:
    result = ranking_result(tmp_path, requested=50)

    assert result["summary"]["source_read_limit"] == 50
    assert result["returned_count"] == 50
