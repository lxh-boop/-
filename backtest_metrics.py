from __future__ import annotations

import numpy as np
import pandas as pd


def calc_annual_return(nav, trading_days=252):
    series = pd.Series(nav).dropna().astype(float)
    if len(series) < 2 or series.iloc[0] <= 0:
        return np.nan
    periods = len(series) - 1
    if periods <= 0:
        return np.nan
    return float((series.iloc[-1] / series.iloc[0]) ** (float(trading_days) / periods) - 1.0)


def calc_annual_volatility(daily_returns, trading_days=252):
    returns = pd.Series(daily_returns).dropna().astype(float)
    if len(returns) < 2:
        return np.nan
    return float(returns.std(ddof=1) * np.sqrt(float(trading_days)))


def calc_sharpe(daily_returns, trading_days=252):
    returns = pd.Series(daily_returns).dropna().astype(float)
    if len(returns) < 2:
        return np.nan
    vol = returns.std(ddof=1)
    if vol <= 1e-12:
        return np.nan
    return float(returns.mean() / vol * np.sqrt(float(trading_days)))


def calc_max_drawdown(nav):
    series = pd.Series(nav).dropna().astype(float)
    if series.empty:
        return np.nan
    running_max = series.cummax()
    drawdown = series / running_max - 1.0
    return float(drawdown.min())


def calc_win_rate(daily_returns):
    returns = pd.Series(daily_returns).dropna().astype(float)
    if returns.empty:
        return np.nan
    return float((returns > 0).mean())


def calc_ic(pred, target):
    x = pd.Series(pred).astype(float)
    y = pd.Series(target).astype(float)
    mask = x.notna() & y.notna()
    x = x[mask]
    y = y[mask]
    if len(x) < 3 or x.std(ddof=0) <= 1e-12 or y.std(ddof=0) <= 1e-12:
        return np.nan
    return float(x.corr(y))


def calc_rankic(pred, target):
    x = pd.Series(pred).astype(float)
    y = pd.Series(target).astype(float)
    mask = x.notna() & y.notna()
    x = x[mask]
    y = y[mask]
    if len(x) < 3:
        return np.nan
    return float(x.rank().corr(y.rank()))


def calc_daily_ic_table(pred_df, pred_col="raw_score", target_col="future_5d_ret"):
    rows = []
    if pred_df is None or pred_df.empty:
        return pd.DataFrame(columns=["date", "IC", "RankIC"])

    for date, group in pred_df.groupby("date"):
        rows.append(
            {
                "date": date,
                "IC": calc_ic(group[pred_col], group[target_col]),
                "RankIC": calc_rankic(group[pred_col], group[target_col]),
            }
        )
    return pd.DataFrame(rows)


def summarize_ic(pred_df, pred_col="raw_score", target_col="future_5d_ret"):
    daily = calc_daily_ic_table(pred_df, pred_col=pred_col, target_col=target_col)
    ic = pd.to_numeric(daily.get("IC", pd.Series(dtype=float)), errors="coerce").dropna()
    rankic = pd.to_numeric(daily.get("RankIC", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "IC": float(ic.mean()) if not ic.empty else np.nan,
        "RankIC": float(rankic.mean()) if not rankic.empty else np.nan,
        "ICIR": float(ic.mean() / ic.std(ddof=1)) if len(ic) > 1 and ic.std(ddof=1) > 1e-12 else np.nan,
        "RankICIR": (
            float(rankic.mean() / rankic.std(ddof=1))
            if len(rankic) > 1 and rankic.std(ddof=1) > 1e-12
            else np.nan
        ),
    }
