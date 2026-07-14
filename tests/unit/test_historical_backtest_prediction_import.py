import pandas as pd

from pipelines.historical_signal_importer import import_historical_signals


def test_historical_backtest_prediction_import_writes_daily_ranking(tmp_path) -> None:
    source = tmp_path / "predictions.csv"
    pd.DataFrame(
        [
            {"trade_date": "2026-04-01", "code": "1", "name": "A", "score": 0.8, "close": 10.0},
            {"trade_date": "2026-04-01", "code": "2", "name": "B", "score": 0.9, "close": 20.0},
        ]
    ).to_csv(source, index=False)

    result = import_historical_signals(source, "2026-04-01", "2026-04-01", output_dir=tmp_path)
    ranking = pd.read_csv(tmp_path / "rankings" / "history" / "ranking_20260401.csv", dtype={"stock_code": str})

    assert result.imported_ranking_dates == 1
    assert ranking.iloc[0]["stock_code"] == "000002"
    assert ranking.iloc[0]["original_rank"] == 1
    assert ranking.iloc[0]["source"] == "historical_backtest_prediction"
