import pandas as pd

from pipelines.historical_prediction_loader import load_historical_predictions
from pipelines.historical_signal_importer import import_historical_signals


def test_backfill_loader_uses_imported_backtest_ranking(tmp_path) -> None:
    source = tmp_path / "backtest_daily_predictions.csv"
    pd.DataFrame(
        [
            {"trade_date": "2026-04-01", "code": "000001", "score": 0.9, "close": 10.0},
            {"trade_date": "2026-04-01", "code": "000002", "score": 0.8, "close": 20.0},
        ]
    ).to_csv(source, index=False)
    import_historical_signals(source, "2026-04-01", "2026-04-01", output_dir=tmp_path)

    result = load_historical_predictions("2026-04-01", user_id="u1", output_dir=tmp_path, top_k=10)

    assert result.status == "success"
    assert result.source.endswith("ranking_20260401.csv")
    assert result.predictions[0].stock_code == "000001"
