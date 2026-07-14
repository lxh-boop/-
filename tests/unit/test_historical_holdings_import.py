import pandas as pd

from pipelines.historical_signal_importer import import_historical_holdings


def test_historical_holdings_import_marks_source(tmp_path) -> None:
    source = tmp_path / "trades.csv"
    pd.DataFrame(
        [
            {"trade_date": "2026-04-01", "code": "1", "weight": 0.1},
            {"trade_date": "2026-04-01", "code": "2", "weight": 0.1},
        ]
    ).to_csv(source, index=False)

    result = import_historical_holdings(source, "2026-04-01", "2026-04-01", output_dir=tmp_path)
    holdings = pd.read_csv(tmp_path / "rankings" / "history" / "holdings_20260401.csv", dtype={"stock_code": str})

    assert result.restored_holding_dates == 1
    assert set(holdings["source"]) == {"historical_backtest_holdings"}
