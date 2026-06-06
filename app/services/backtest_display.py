from __future__ import annotations

import pandas as pd


def build_display_date_options(
    backtest_trades: pd.DataFrame | None,
    ranking_df: pd.DataFrame | None,
) -> tuple[list[str], str | None]:
    trade_dates: list[str] = []
    if backtest_trades is not None and not backtest_trades.empty and "date" in backtest_trades.columns:
        trade_dates = sorted(backtest_trades["date"].astype(str).dropna().unique().tolist(), reverse=True)

    latest_prediction_date = None
    if ranking_df is not None and not ranking_df.empty and "date" in ranking_df.columns:
        parsed = pd.to_datetime(ranking_df["date"], errors="coerce").dropna()
        if not parsed.empty:
            latest_prediction_date = str(parsed.max().date())

    options = list(trade_dates)
    if latest_prediction_date and latest_prediction_date not in options:
        options.insert(0, latest_prediction_date)

    return options, latest_prediction_date


def is_prediction_only_date(
    selected_date: str,
    backtest_trades: pd.DataFrame | None,
) -> bool:
    if backtest_trades is None or backtest_trades.empty or "date" not in backtest_trades.columns:
        return True
    available = set(backtest_trades["date"].astype(str).dropna().unique().tolist())
    return str(selected_date) not in available
