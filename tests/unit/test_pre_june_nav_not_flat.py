import pandas as pd

from pipelines.historical_signal_importer import import_historical_signals
from pipelines.paper_backfill_pipeline import run_paper_trading_backfill


def test_pre_june_composite_nav_is_not_flat_when_history_signals_exist(tmp_path) -> None:
    rows = []
    for trade_date, price in [("2026-04-01", 10.0), ("2026-04-02", 11.0), ("2026-04-03", 12.0)]:
        for index in range(1, 11):
            rows.append(
                {
                    "trade_date": trade_date,
                    "code": f"{index:06d}",
                    "name": f"S{index}",
                    "score": 1.0 - index * 0.01,
                    "close": price + index,
                }
            )
    source = tmp_path / "backtest_daily_predictions.csv"
    pd.DataFrame(rows).to_csv(source, index=False)
    import_historical_signals(source, "2026-04-01", "2026-04-03", output_dir=tmp_path)

    result = run_paper_trading_backfill(
        user_id="u1",
        start_date="2026-04-01",
        end_date="2026-04-03",
        force=True,
        resume=False,
        skip_news=True,
        output_dir=tmp_path,
        db_path=tmp_path / "agent.db",
    )

    nav = pd.read_csv(tmp_path / "portfolio" / "u1" / "paper_nav_latest.csv")
    assert result.failed_days == 0
    assert "composite_nav" in nav.columns
    assert nav["composite_nav"].nunique() > 1
