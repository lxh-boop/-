from top_k_test_helpers import ranking_result


def test_top_k_reads_exact_limit(tmp_path) -> None:
    result = ranking_result(tmp_path, requested=10)

    assert result["summary"]["source_read_limit"] == 10
    assert result["summary"]["top_k"] == 10
    assert len(result["records"]) == 10
