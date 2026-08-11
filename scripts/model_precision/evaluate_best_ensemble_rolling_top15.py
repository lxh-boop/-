from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import lightgbm as lgb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
)
DEFAULT_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
)
DEFAULT_FEATURE_REPORT = (
    ROOT / "outputs" / "model_precision" / "stock_top15_feature_subset_search.json"
)
DEFAULT_REPORT = (
    ROOT / "outputs" / "model_precision" / "stock_top15_best_ensemble_rolling.json"
)
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_best_ensemble_rolling.parquet"
)
DEFAULT_CHECKPOINT_DIR = (
    ROOT / "data" / "model_precision" / "stock_top15_best_ensemble_rolling_parts"
)


@dataclass(frozen=True)
class ModelSpec:
    name: str
    column_order: str
    seed: int
    iterations: int
    weight: float


MODEL_SPECS = (
    ModelSpec("seed101", "base", 101, 120, 0.1647813272195915),
    ModelSpec("gain_order", "gain", 101, 160, 0.673005517829718),
    ModelSpec("seed149", "base", 149, 120, 0.02817242825489619),
    ModelSpec("seed23", "base", 23, 160, 0.13404072669579434),
)


def _atomic_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def _parameters(seed: int, num_threads: int) -> dict[str, object]:
    return {
        "objective": "lambdarank",
        "metric": "ndcg",
        "ndcg_eval_at": [15],
        "lambdarank_truncation_level": 50,
        "learning_rate": 0.025,
        "num_leaves": 15,
        "max_depth": 4,
        "min_child_samples": 80,
        "feature_fraction": 0.90,
        "bagging_fraction": 0.85,
        "bagging_freq": 1,
        "lambda_l1": 0.3,
        "lambda_l2": 2.0,
        "seed": seed,
        "feature_fraction_seed": seed,
        "bagging_seed": seed,
        "data_random_seed": seed,
        "feature_pre_filter": False,
        "verbosity": -1,
        "num_threads": num_threads,
    }


def rolling_periods(
    evaluation_dates: Iterable[pd.Timestamp],
    *,
    retrain_every: int,
    daily_from: pd.Timestamp | None,
) -> list[list[pd.Timestamp]]:
    """Split ordered trading dates into retraining periods.

    The cadence restarts when daily mode begins so a period can never straddle the
    policy boundary.
    """

    if retrain_every < 1:
        raise ValueError("retrain_every must be at least 1")
    dates = sorted({pd.Timestamp(value).normalize() for value in evaluation_dates})
    before = [value for value in dates if daily_from is None or value < daily_from]
    after = [value for value in dates if daily_from is not None and value >= daily_from]
    periods = [before[index : index + retrain_every] for index in range(0, len(before), retrain_every)]
    periods.extend([[value] for value in after])
    return [period for period in periods if period]


def _metrics(frame: pd.DataFrame, score_column: str) -> dict[str, Any]:
    top = (
        frame.sort_values(
            ["date", score_column, "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    counts = top.groupby("date", sort=True).size()
    daily = top.groupby("date", sort=True)["label_up"].mean()
    monthly = top.assign(month=top["date"].dt.to_period("M").astype(str)).groupby(
        "month", sort=True
    )["label_up"].agg(signals="size", correct="sum", precision="mean")
    return {
        "start_date": str(daily.index.min().date()) if not daily.empty else None,
        "end_date": str(daily.index.max().date()) if not daily.empty else None,
        "days": int(len(daily)),
        "signals": int(len(top)),
        "correct": int(top["label_up"].sum()),
        "precision": float(daily.mean()) if not daily.empty else None,
        "all_days_have_15": bool(not counts.empty and counts.eq(15).all()),
        "monthly": [
            {
                "month": str(month),
                "signals": int(row["signals"]),
                "correct": int(row["correct"]),
                "precision": float(row["precision"]),
            }
            for month, row in monthly.iterrows()
        ],
    }


def _configuration_id(
    args: argparse.Namespace,
    base_columns: list[str],
    model_specs: tuple[ModelSpec, ...],
) -> str:
    payload = {
        "implementation_version": 2,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "retrain_every": args.retrain_every,
        "daily_from": args.daily_from,
        "training_years": args.training_years,
        "columns": base_columns,
        "model_set": args.model_set,
        "models": [spec.__dict__ for spec in model_specs],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _checkpoint_path(checkpoint_dir: Path, configuration_id: str, start: pd.Timestamp) -> Path:
    return checkpoint_dir / configuration_id / f"{start:%Y%m%d}.parquet"


def _load_feature_orders(
    data: pd.DataFrame, columns_path: Path, feature_report_path: Path
) -> tuple[list[str], list[str]]:
    base = [
        value
        for value in columns_path.read_text(encoding="utf-8").splitlines()
        if value and value in data.columns
    ]
    if not base:
        raise RuntimeError("No usable feature columns were found")
    report = json.loads(feature_report_path.read_text(encoding="utf-8"))
    gain = next(
        (
            [value for value in row["features"] if value in data.columns]
            for row in report["results"]
            if int(row["feature_count"]) == len(base)
        ),
        None,
    )
    if gain is None or set(gain) != set(base):
        raise RuntimeError("The gain-ordered feature set does not match the base feature set")
    return base, gain


def _train_period(
    *,
    data: pd.DataFrame,
    period_dates: list[pd.Timestamp],
    base_columns: list[str],
    gain_columns: list[str],
    model_specs: tuple[ModelSpec, ...],
    training_years: int,
    num_threads: int,
) -> pd.DataFrame:
    score_start = period_dates[0]
    score_end = period_dates[-1]
    training = data[data["date"].lt(score_start)]
    if training_years > 0:
        train_start = score_start - pd.DateOffset(years=training_years)
        training = training[training["date"].ge(train_start)]
    evaluation = data[data["date"].isin(period_dates)].copy()
    if training.empty or evaluation.empty:
        raise RuntimeError(f"Empty training or evaluation data for {score_start.date()}")
    if training["date"].max() >= score_start:
        raise AssertionError("Training features overlap the evaluation period")

    groups = training.groupby("date", sort=False).size().to_numpy()
    labels = training["label_up"].astype(int)
    column_orders = {"base": base_columns, "gain": gain_columns}
    for spec in model_specs:
        # data_random_seed is a Dataset construction parameter in LightGBM. Each
        # ensemble member therefore needs its own Dataset to reproduce the model
        # selected during the original seed search.
        dataset = lgb.Dataset(
            training[column_orders[spec.column_order]],
            label=labels,
            group=groups,
            params={
                "data_random_seed": spec.seed,
                "feature_pre_filter": False,
            },
            free_raw_data=True,
        )
        model = lgb.train(
            _parameters(spec.seed, num_threads),
            dataset,
            num_boost_round=spec.iterations,
            callbacks=[lgb.log_evaluation(0)],
        )
        evaluation[spec.name] = model.predict(
            evaluation[column_orders[spec.column_order]]
        ).astype("float32")
        del model, dataset
        gc.collect()

    score_columns = [spec.name for spec in model_specs]
    if len(model_specs) == 1:
        evaluation["ensemble_score"] = evaluation[model_specs[0].name]
    else:
        weights = pd.Series({spec.name: spec.weight for spec in model_specs})
        within_day_ranks = evaluation.groupby("date", sort=False)[score_columns].rank(
            pct=True
        )
        evaluation["ensemble_score"] = within_day_ranks.mul(weights, axis=1).sum(
            axis=1
        )
    evaluation["train_start"] = training["date"].min()
    evaluation["train_end"] = training["date"].max()
    evaluation["score_period_start"] = score_start
    evaluation["score_period_end"] = score_end
    return evaluation.loc[
        :,
        [
            "date",
            "code",
            "label_up",
            "pred_return",
            *score_columns,
            "ensemble_score",
            "train_start",
            "train_end",
            "score_period_start",
            "score_period_end",
        ],
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict rolling walk-forward evaluation of the best Top15 ensemble."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_COLUMNS)
    parser.add_argument("--feature-report", type=Path, default=DEFAULT_FEATURE_REPORT)
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2026-12-31")
    parser.add_argument(
        "--retrain-every",
        type=int,
        default=10,
        help="Retrain after this many trading days before --daily-from.",
    )
    parser.add_argument(
        "--daily-from",
        default="2026-01-01",
        help="Retrain every trading day on/after this date; use an empty value to disable.",
    )
    parser.add_argument(
        "--training-years",
        type=int,
        default=0,
        help="Trailing training window in years; 0 uses all prior observations.",
    )
    parser.add_argument("--num-threads", type=int, default=-1)
    parser.add_argument(
        "--model-set",
        choices=("ensemble", "seed101"),
        default="ensemble",
        help="Train the full selected ensemble or only its strongest single member.",
    )
    parser.add_argument("--target-precision", type=float, default=0.55)
    parser.add_argument("--checkpoint-dir", type=Path, default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.training_years < 0:
        raise ValueError("training_years cannot be negative")
    data = pd.read_parquet(args.feature_cache)
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data = data[data["label_up"].notna()].sort_values(["date", "code"], kind="stable")
    base_columns, gain_columns = _load_feature_orders(
        data, args.feature_columns, args.feature_report
    )
    model_specs = (
        MODEL_SPECS
        if args.model_set == "ensemble"
        else tuple(spec for spec in MODEL_SPECS if spec.name == args.model_set)
    )
    evaluation_mask = data["date"].between(args.start_date, args.end_date)
    evaluation_dates = data.loc[evaluation_mask, "date"].drop_duplicates().tolist()
    if not evaluation_dates:
        raise RuntimeError("No evaluation dates were found")
    daily_from = pd.Timestamp(args.daily_from).normalize() if args.daily_from else None
    periods = rolling_periods(
        evaluation_dates,
        retrain_every=int(args.retrain_every),
        daily_from=daily_from,
    )
    configuration_id = _configuration_id(args, base_columns, model_specs)
    scored_parts: list[pd.DataFrame] = []
    period_reports: list[dict[str, Any]] = []
    for index, period_dates in enumerate(periods, start=1):
        checkpoint = _checkpoint_path(
            args.checkpoint_dir, configuration_id, period_dates[0]
        )
        if checkpoint.exists() and not args.no_resume:
            scored = pd.read_parquet(checkpoint)
            source = "checkpoint"
        else:
            print(
                f"[{index}/{len(periods)}] train before {period_dates[0].date()} "
                f"and score through {period_dates[-1].date()}",
                flush=True,
            )
            scored = _train_period(
                data=data,
                period_dates=period_dates,
                base_columns=base_columns,
                gain_columns=gain_columns,
                model_specs=model_specs,
                training_years=int(args.training_years),
                num_threads=int(args.num_threads),
            )
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            temporary = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
            scored.to_parquet(temporary, index=False)
            os.replace(temporary, checkpoint)
            source = "trained"
        if scored["train_end"].max() >= scored["date"].min():
            raise AssertionError("Checkpoint violates the strict time-order contract")
        scored_parts.append(scored)
        period_reports.append(
            {
                "score_start": str(scored["date"].min().date()),
                "score_end": str(scored["date"].max().date()),
                "train_start": str(pd.Timestamp(scored["train_start"].min()).date()),
                "train_end": str(pd.Timestamp(scored["train_end"].max()).date()),
                "source": source,
                **_metrics(scored, "ensemble_score"),
            }
        )

    predictions = pd.concat(scored_parts, ignore_index=True).sort_values(
        ["date", "code"], kind="stable"
    )
    overall = _metrics(predictions, "ensemble_score")
    baseline = _metrics(predictions, "pred_return")
    yearly = {
        str(year): _metrics(frame, "ensemble_score")
        for year, frame in predictions.groupby(predictions["date"].dt.year, sort=True)
    }
    baseline_yearly = {
        str(year): _metrics(frame, "pred_return")
        for year, frame in predictions.groupby(predictions["date"].dt.year, sort=True)
    }
    member_metrics = {
        spec.name: {
            "overall": _metrics(predictions, spec.name),
            "yearly": {
                str(year): _metrics(frame, spec.name)
                for year, frame in predictions.groupby(
                    predictions["date"].dt.year, sort=True
                )
            },
        }
        for spec in model_specs
    }
    target = float(args.target_precision)
    accepted = bool(
        overall["all_days_have_15"]
        and yearly
        and all(row["precision"] is not None and row["precision"] >= target for row in yearly.values())
    )
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "strict_rolling_best_ensemble_fixed_daily_top15_precision",
        "accepted": accepted,
        "target_precision": target,
        "selection_count_per_day": 15,
        "abstention_allowed": False,
        "configuration_id": configuration_id,
        "schedule": {
            "start_date": args.start_date,
            "end_date": args.end_date,
            "retrain_every_before_daily_mode": int(args.retrain_every),
            "daily_from": args.daily_from or None,
            "training_years": int(args.training_years),
            "period_count": len(periods),
        },
        "feature_count": len(base_columns),
        "model_set": args.model_set,
        "models": [spec.__dict__ for spec in model_specs],
        "data_contract": {
            "label": "future_1d_ret_gt_0",
            "metric": "mean_of_each_days_fixed_top15_precision",
            "training_rows_strictly_before_first_scored_date": True,
            "uses_future_features": False,
        },
        "overall": overall,
        "yearly": yearly,
        "members": member_metrics,
        "pred_return_baseline": {"overall": baseline, "yearly": baseline_yearly},
        "periods": period_reports,
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }
    args.predictions_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_predictions = args.predictions_path.with_suffix(
        args.predictions_path.suffix + ".tmp"
    )
    predictions.to_parquet(temporary_predictions, index=False)
    os.replace(temporary_predictions, args.predictions_path)
    _atomic_json(report, args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if accepted else 2


if __name__ == "__main__":
    raise SystemExit(main())
