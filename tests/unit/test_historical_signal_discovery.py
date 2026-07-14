import pandas as pd

from pipelines.historical_signal_importer import audit_historical_signals


def test_historical_signal_discovery_finds_prediction_and_backtest_files(tmp_path) -> None:
    out = tmp_path / "outputs"
    out.mkdir()
    pd.DataFrame(
        [
            {"trade_date": "2026-04-01", "code": "000001", "score": 0.9, "close": 10.0},
            {"trade_date": "2026-04-01", "code": "000002", "score": 0.8, "close": 20.0},
        ]
    ).to_csv(out / "my_prediction_scores.csv", index=False)
    pd.DataFrame([{"date": "2026-04-01", "nav": 1.01, "net_return": 0.01}]).to_csv(
        out / "daily_returns.csv", index=False
    )

    audit = audit_historical_signals("2026-04-01", "2026-04-01", search_dirs=[out], output_dir=tmp_path)

    assert audit.prediction_files
    assert audit.backtest_files
    assert audit.has_score is True
    assert audit.has_price is True
    assert audit.selected_source.endswith("my_prediction_scores.csv")
