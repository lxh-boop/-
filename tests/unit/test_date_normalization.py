from datetime import date

from pipelines.replay_normalization import normalize_trade_date, normalize_trade_date_text, trade_date_token


def test_date_normalization_accepts_common_trade_date_formats() -> None:
    assert normalize_trade_date("2026-05-08") == date(2026, 5, 8)
    assert normalize_trade_date("2026-05-08 00:00:00") == date(2026, 5, 8)
    assert normalize_trade_date("20260508") == date(2026, 5, 8)
    assert normalize_trade_date("Timestamp('2026-05-08 00:00:00')") == date(2026, 5, 8)
    assert normalize_trade_date_text("20260508") == "2026-05-08"
    assert trade_date_token("2026-05-08") == "20260508"
