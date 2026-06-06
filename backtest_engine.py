from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_metrics import (
    calc_annual_return,
    calc_annual_volatility,
    calc_max_drawdown,
    calc_sharpe,
    calc_win_rate,
    summarize_ic,
)
from backtest_rebalance import calculate_topk_rebalance, format_code_set


BACKTEST_OUTPUT_DIR = Path("outputs") / "backtests"
DAILY_RETURN_COLUMNS = [
    "date",
    "model_name",
    "topk",
    "holding_days",
    "selected_codes",
    "selected_names",
    "mean_pred_5d_ret",
    "mean_future_5d_ret",
    "gross_return",
    "turnover",
    "buy_turnover",
    "sell_turnover",
    "bought_codes",
    "sold_codes",
    "cost",
    "net_return",
    "cum_return",
    "nav",
    "benchmark_return",
    "excess_return",
]


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return None
    return value


def normalize_prediction_frame(pred_df: pd.DataFrame, model_name: str) -> pd.DataFrame:
    if pred_df is None or pred_df.empty:
        raise RuntimeError(f"{model_name} 没有可回测预测结果。")

    out = pred_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["code"] = out["code"].astype(str).str.zfill(6)
    if "name" not in out.columns:
        out["name"] = out["code"]
    if "pred_5d_ret" not in out.columns:
        raise RuntimeError(f"{model_name} 预测结果缺少 pred_5d_ret。")
    if "raw_score" not in out.columns:
        out["raw_score"] = out["pred_5d_ret"]
    if "score" not in out.columns:
        out["score"] = out.groupby("date")["raw_score"].rank(pct=True)
    if "future_5d_ret" not in out.columns:
        raise RuntimeError(f"{model_name} 预测结果缺少 future_5d_ret，不能做历史回测。")

    if "future_1d_ret" not in out.columns and "close" in out.columns:
        out = out.sort_values(["code", "date"]).copy()
        out["close"] = pd.to_numeric(out["close"], errors="coerce")
        out["future_1d_ret"] = out.groupby("code")["close"].shift(-1) / out["close"] - 1.0

    numeric_cols = ["future_5d_ret", "pred_5d_ret", "raw_score", "score"]
    if "future_1d_ret" in out.columns:
        numeric_cols.append("future_1d_ret")

    for col in numeric_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    out["model_name"] = model_name
    return out.dropna(subset=["future_5d_ret", "score"]).sort_values(["date", "score"], ascending=[True, False])


def realized_return_column_for_holding(data: pd.DataFrame, holding_days: int) -> str:
    if int(holding_days) == 1:
        if "future_1d_ret" not in data.columns:
            raise RuntimeError("holding_days=1 需要 future_1d_ret 或 close 字段来计算 T+1 收益。")
        return "future_1d_ret"
    return "future_5d_ret"


def run_topk_backtest(
    pred_df: pd.DataFrame,
    model_name: str,
    topk: int = 30,
    holding_days: int = 1,
    buy_cost: float = 0.0003,
    sell_cost: float = 0.0008,
    stamp_tax: float = 0.001,
    output_dir: str | Path = BACKTEST_OUTPUT_DIR,
) -> tuple[pd.DataFrame, dict]:
    data = normalize_prediction_frame(pred_df, model_name=model_name)
    topk = int(topk)
    holding_days = int(holding_days)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    previous_codes: set[str] = set()
    nav = 1.0
    realized_col = realized_return_column_for_holding(data, holding_days)
    data = data.dropna(subset=[realized_col]).copy()
    if data.empty:
        raise RuntimeError(f"{model_name} holding_days={holding_days} 没有可评估真实收益。")

    dates = pd.Series(pd.to_datetime(data["date"].unique())).sort_values().tolist()
    rebalance_dates = dates[:: max(holding_days, 1)]

    for date in rebalance_dates:
        group = data[data["date"] == date].copy()
        selected = group.sort_values(["score", "raw_score"], ascending=[False, False]).head(topk).copy()
        if selected.empty:
            continue

        codes = selected["code"].astype(str).str.zfill(6).tolist()
        names = selected["name"].astype(str).tolist()
        rebalance = calculate_topk_rebalance(previous_codes, codes)
        current_codes = rebalance.current_codes

        gross_return = float(selected[realized_col].mean())
        cost = float(
            rebalance.buy_turnover * buy_cost
            + rebalance.sell_turnover * (sell_cost + stamp_tax)
        )
        net_return = gross_return - cost
        nav *= 1.0 + net_return
        benchmark_return = float(group[realized_col].mean())

        rows.append(
            {
                "date": pd.to_datetime(date).strftime("%Y-%m-%d"),
                "model_name": model_name,
                "topk": topk,
                "holding_days": holding_days,
                "selected_codes": ",".join(codes),
                "selected_names": ",".join(names),
                "mean_pred_5d_ret": float(selected["pred_5d_ret"].mean()),
                "mean_future_5d_ret": gross_return,
                "gross_return": gross_return,
                "turnover": rebalance.turnover,
                "buy_turnover": rebalance.buy_turnover,
                "sell_turnover": rebalance.sell_turnover,
                "bought_codes": format_code_set(rebalance.bought_codes),
                "sold_codes": format_code_set(rebalance.sold_codes),
                "cost": cost,
                "net_return": net_return,
                "cum_return": nav - 1.0,
                "nav": nav,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
            }
        )
        previous_codes = current_codes

    daily = pd.DataFrame(rows, columns=DAILY_RETURN_COLUMNS)
    if daily.empty:
        raise RuntimeError(f"{model_name} Top{topk} 没有生成任何回测日收益。")

    periods_per_year = 252 / max(holding_days, 1)
    ic_data = data.copy()
    if realized_col != "future_5d_ret":
        ic_data["future_5d_ret"] = ic_data[realized_col]
    ic_metrics = summarize_ic(ic_data)
    metrics = {
        "model_name": model_name,
        "topk": topk,
        "holding_days": holding_days,
        "start_date": daily["date"].min(),
        "end_date": daily["date"].max(),
        "num_days": int(len(daily)),
        "annual_return": calc_annual_return(pd.concat([pd.Series([1.0]), daily["nav"]]), trading_days=periods_per_year),
        "annual_volatility": calc_annual_volatility(daily["net_return"], trading_days=periods_per_year),
        "sharpe": calc_sharpe(daily["net_return"], trading_days=periods_per_year),
        "max_drawdown": calc_max_drawdown(pd.concat([pd.Series([1.0]), daily["nav"]])),
        "win_rate": calc_win_rate(daily["net_return"]),
        "mean_daily_return": float(daily["net_return"].mean()),
        "std_daily_return": float(daily["net_return"].std(ddof=1)) if len(daily) > 1 else np.nan,
        "cum_return": float(daily["cum_return"].iloc[-1]),
        "final_nav": float(daily["nav"].iloc[-1]),
        "mean_turnover": float(daily["turnover"].mean()),
        "mean_cost": float(daily["cost"].mean()),
        "mean_topk_future_ret": float(daily["mean_future_5d_ret"].mean()),
        **ic_metrics,
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }

    daily_path = output_dir / f"{model_name}_top{topk}_daily_returns.csv"
    metrics_path = output_dir / f"{model_name}_top{topk}_metrics.json"
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")
    metrics_path.write_text(json.dumps(_jsonable(metrics), ensure_ascii=False, indent=2), encoding="utf-8")
    return daily, metrics


def update_backtest_summary(metrics_list: list[dict], output_dir: str | Path = BACKTEST_OUTPUT_DIR) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "backtest_summary.csv"
    new_df = pd.DataFrame(metrics_list)

    if summary_path.exists():
        old_df = pd.read_csv(summary_path, encoding="utf-8-sig")
        combined = pd.concat([old_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(["model_name", "topk", "holding_days"], keep="last")
    else:
        combined = new_df

    combined.to_csv(summary_path, index=False, encoding="utf-8-sig")
    return summary_path
