from pipelines.replay_normalization import normalize_stock_code


def test_stock_code_normalization_uses_project_six_digit_format() -> None:
    assert normalize_stock_code("000001") == "000001"
    assert normalize_stock_code("000001.SZ") == "000001"
    assert normalize_stock_code("SZ000001") == "000001"
    assert normalize_stock_code("600000.SH") == "600000"
    assert normalize_stock_code("SH600000") == "600000"
    assert normalize_stock_code("") == ""
