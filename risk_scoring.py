from __future__ import annotations

import json

import numpy as np
import pandas as pd


RISK_COMPONENT_WEIGHTS = {
    "realized_volatility_component": 0.30,
    "drawdown_component": 0.25,
    "liquidity_component": 0.20,
    "recent_return_shock_component": 0.15,
    "news_risk_component": 0.10,
}


def _numeric(series, default: float = 0.0, index=None) -> pd.Series:
    if not isinstance(series, pd.Series):
        series = pd.Series(series, index=index)
    result = pd.to_numeric(series, errors="coerce")
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=series.index)
    return result.replace([np.inf, -np.inf], np.nan).fillna(default)


def _rank01(series: pd.Series, ascending: bool = True, default: float = 0.5) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)

    if values.notna().sum() < 2 or values.nunique(dropna=True) < 2:
        return pd.Series(default, index=series.index, dtype=float)

    return values.rank(pct=True, ascending=ascending).fillna(default).astype(float)


def _extract_components(df: pd.DataFrame) -> pd.DataFrame:
    components = pd.DataFrame(index=df.index)

    vol = _numeric(df.get("vol_20", 0.0), index=df.index)
    drawdown = _numeric(df.get("drawdown_20", 0.0), index=df.index)

    if "amount" in df.columns:
        liquidity_source = _numeric(df["amount"], index=df.index)
    elif "volume" in df.columns:
        liquidity_source = _numeric(df["volume"], index=df.index)
    else:
        liquidity_source = pd.Series(np.nan, index=df.index)

    if "pct_chg" in df.columns:
        shock_source = _numeric(df["pct_chg"], index=df.index).abs()
    elif "ret_5" in df.columns:
        shock_source = _numeric(df["ret_5"], index=df.index).abs()
    else:
        shock_source = pd.Series(0.0, index=df.index)

    news_risk = _numeric(df.get("risk_event_count_5d", 0.0), index=df.index) + _numeric(
        df.get("negative_event_count_5d", 0.0), index=df.index
    )

    components["realized_volatility_component"] = _rank01(vol, ascending=True)
    components["drawdown_component"] = _rank01(-drawdown, ascending=True)
    components["liquidity_component"] = 1.0 - _rank01(liquidity_source, ascending=True)
    components["recent_return_shock_component"] = _rank01(shock_source, ascending=True)
    components["news_risk_component"] = _rank01(news_risk, ascending=True, default=0.0)

    return components.clip(0.0, 1.0)


def _risk_level_from_scores(scores: pd.Series) -> pd.Series:
    scores = pd.to_numeric(scores, errors="coerce").fillna(0.5)

    if scores.nunique(dropna=True) < 2:
        return pd.Series("中", index=scores.index)

    high_cut = scores.quantile(0.80)
    mid_cut = scores.quantile(0.50)

    return pd.Series(
        np.where(scores >= high_cut, "高", np.where(scores >= mid_cut, "中", "低")),
        index=scores.index,
    )


def add_risk_scores(ranking_or_latest_df: pd.DataFrame) -> pd.DataFrame:
    df = ranking_or_latest_df.copy()

    if df.empty:
        df["risk_score"] = []
        df["risk_level"] = []
        df["risk_detail"] = []
        return df

    components = _extract_components(df)
    risk_score = pd.Series(0.0, index=df.index, dtype=float)

    for col, weight in RISK_COMPONENT_WEIGHTS.items():
        risk_score += components[col] * float(weight)

    df["risk_score"] = risk_score.clip(0.0, 1.0)
    df["risk_level"] = _risk_level_from_scores(df["risk_score"])

    details = []
    for idx in df.index:
        detail = {
            "risk_score": round(float(df.at[idx, "risk_score"]), 6),
            "risk_level_rule": "CSI300 cross-sectional percentile: >=80% high, 50%-80% medium, <50% low",
            "components": {
                col: round(float(components.at[idx, col]), 6)
                for col in components.columns
            },
            "weights": RISK_COMPONENT_WEIGHTS,
        }
        details.append(json.dumps(detail, ensure_ascii=False))

    df["risk_detail"] = details
    return df
