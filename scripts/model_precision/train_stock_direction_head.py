from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import pandas as pd
from lightgbm import LGBMRanker


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kronos_runtime.stock_direction_features import build_stock_direction_dataset


DEFAULT_PREDICTIONS = (
    ROOT
    / "outputs"
    / "backtests"
    / "predictions"
    / "target_full_recent_v1_kronos_mini_t1_predictions.csv"
)
DEFAULT_MARKET_HISTORY = ROOT / "data" / "kronos_market_history.csv"
DEFAULT_FEATURE_DIR = ROOT / "data" / "model_precision" / "tushare"
DEFAULT_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_evaluation_report.json"
DEFAULT_MODEL = ROOT / "models" / "kronos_mini" / "stock_direction_head.joblib"


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_joblib(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        joblib.dump(payload, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _top15_metrics(scored: pd.DataFrame, score_column: str) -> dict[str, Any]:
    top = (
        scored.sort_values(
            ["date", score_column, "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    daily = top.groupby("date", sort=True)["label_up"].mean()
    monthly = (
        top.assign(month=top["date"].dt.to_period("M").astype(str))
        .groupby("month", sort=True)["label_up"]
        .agg(signals="size", correct="sum", precision="mean")
    )
    return {
        "days": int(len(daily)),
        "signals": int(len(top)),
        "correct": int(top["label_up"].sum()),
        "daily_average_precision": float(daily.mean()),
        "start_date": str(daily.index.min().date()),
        "end_date": str(daily.index.max().date()),
        "all_days_have_15": bool(daily.notna().all() and len(top) == len(daily) * 15),
        "monthly": [
            {
                "month": str(index),
                "signals": int(row["signals"]),
                "correct": int(row["correct"]),
                "precision": float(row["precision"]),
            }
            for index, row in monthly.iterrows()
        ],
    }


def _model(iterations: int) -> LGBMRanker:
    return LGBMRanker(
        objective="rank_xendcg",
        metric="ndcg",
        eval_at=[15],
        n_estimators=int(iterations),
        learning_rate=0.025,
        num_leaves=31,
        max_depth=6,
        min_child_samples=120,
        subsample=0.85,
        colsample_bytree=0.70,
        reg_alpha=0.30,
        reg_lambda=2.0,
        random_state=61,
        n_jobs=-1,
        verbosity=-1,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="训练并严格验收每日固定Top15的股票级T+1上涨排序头。"
    )
    parser.add_argument("--prediction-history", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--market-history", type=Path, default=DEFAULT_MARKET_HISTORY)
    parser.add_argument("--feature-dir", type=Path, default=DEFAULT_FEATURE_DIR)
    parser.add_argument("--feature-cache", type=Path, default=None)
    parser.add_argument("--feature-columns", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--target-precision", type=float, default=0.55)
    parser.add_argument(
        "--fixed-iterations",
        type=int,
        default=0,
        help="复核已在验证集确定的迭代数；0表示重新早停选择。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.feature_cache and args.feature_cache.exists():
        data = pd.read_parquet(args.feature_cache)
        if not args.feature_columns or not args.feature_columns.exists():
            raise FileNotFoundError("使用feature-cache时必须提供feature-columns")
        feature_columns = [
            value
            for value in args.feature_columns.read_text(encoding="utf-8").splitlines()
            if value
        ]
    else:
        data, feature_columns = build_stock_direction_dataset(
            prediction_history_path=args.prediction_history,
            market_history_path=args.market_history,
            tushare_feature_dir=args.feature_dir,
        )
    data = data[data["label_up"].notna()].copy()
    train = data[data["date"].le("2024-12-31")].copy()
    validation = data[
        data["date"].gt("2024-12-31") & data["date"].le("2025-12-31")
    ].copy()
    holdout = data[data["date"].gt("2025-12-31")].copy()
    if train.empty or validation.empty or holdout.empty:
        raise RuntimeError("训练、验证或留出区间为空")

    fixed_iterations = max(0, int(args.fixed_iterations))
    validation_model = _model(fixed_iterations or 800)
    fit_kwargs: dict[str, Any] = {}
    if not fixed_iterations:
        fit_kwargs = {
            "eval_set": [
                (validation[feature_columns], validation["label_up"].astype(int))
            ],
            "eval_group": [
                validation.groupby("date", sort=False).size().to_numpy()
            ],
            "callbacks": [
                lgb.early_stopping(70, verbose=False),
                lgb.log_evaluation(0),
            ],
        }
    validation_model.fit(
        train[feature_columns],
        train["label_up"].astype(int),
        group=train.groupby("date", sort=False).size().to_numpy(),
        **fit_kwargs,
    )
    best_iteration = fixed_iterations or int(validation_model.best_iteration_ or 1)
    validation["stock_up_score"] = validation_model.predict(
        validation[feature_columns],
        num_iteration=best_iteration,
    )
    validation_metrics = _top15_metrics(validation, "stock_up_score")

    combined_train = data[data["date"].le("2025-12-31")].copy()
    holdout_model = _model(best_iteration)
    holdout_model.fit(
        combined_train[feature_columns],
        combined_train["label_up"].astype(int),
        group=combined_train.groupby("date", sort=False).size().to_numpy(),
    )
    holdout["stock_up_score"] = holdout_model.predict(holdout[feature_columns])
    holdout_metrics = _top15_metrics(holdout, "stock_up_score")

    for split in (validation, holdout):
        split["pred_return_baseline"] = split["pred_return"]
    baselines = {
        "validation_pred_return_top15": _top15_metrics(
            validation, "pred_return_baseline"
        ),
        "holdout_pred_return_top15": _top15_metrics(holdout, "pred_return_baseline"),
    }
    accepted = bool(
        validation_metrics["all_days_have_15"]
        and holdout_metrics["all_days_have_15"]
        and validation_metrics["daily_average_precision"] >= float(args.target_precision)
        and holdout_metrics["daily_average_precision"] >= float(args.target_precision)
    )
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "accepted": accepted,
        "objective": "fixed_daily_stock_top15_next_trading_day_up_precision",
        "target_precision": float(args.target_precision),
        "selection_count_per_day": 15,
        "abstention_allowed": False,
        "feature_count": len(feature_columns),
        "best_iteration": best_iteration,
        "training": {
            "start_date": str(train["date"].min().date()),
            "end_date": str(train["date"].max().date()),
            "days": int(train["date"].nunique()),
            "rows": int(len(train)),
        },
        "validation": validation_metrics,
        "holdout": holdout_metrics,
        "baselines": baselines,
        "data_contract": {
            "label": "future_1d_ret_gt_0",
            "metric": "mean_of_daily_top15_precision",
            "uses_future_features": False,
            "tushare_token_persisted": False,
        },
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }
    _atomic_json(report, Path(args.report_path))
    if accepted:
        _atomic_joblib(
            {
                "model": holdout_model,
                "feature_columns": feature_columns,
                "top_k": 15,
                "target_precision": float(args.target_precision),
                "trained_through": str(combined_train["date"].max().date()),
            },
            Path(args.model_path),
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
