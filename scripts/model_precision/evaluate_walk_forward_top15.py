from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_CACHE = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
)
DEFAULT_FEATURE_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
)
DEFAULT_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_walk_forward.json"
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_walk_forward_predictions.parquet"
)


def _periods(year: int) -> list[tuple[str, str, str]]:
    return [
        (f"{year}-01-01", f"{year}-03-31", f"{year-1}-12-31"),
        (f"{year}-04-01", f"{year}-06-30", f"{year}-03-31"),
        (f"{year}-07-01", f"{year}-09-30", f"{year}-06-30"),
        (f"{year}-10-01", f"{year}-12-31", f"{year}-09-30"),
    ]


def _model_parameters(seed: int) -> dict[str, object]:
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
        "num_threads": -1,
    }


def _score_metrics(scored: pd.DataFrame) -> dict[str, object]:
    top = (
        scored.sort_values(
            ["date", "score", "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    daily = top.groupby("date", sort=True)["label_up"].mean()
    counts = top.groupby("date", sort=True).size()
    return {
        "days": int(len(daily)),
        "signals": int(len(top)),
        "correct": int(top["label_up"].sum()),
        "precision": float(daily.mean()),
        "all_days_have_15": bool(not daily.empty and counts.eq(15).all()),
        "monthly": {
            str(month): float(value)
            for month, value in top.groupby(top["date"].dt.to_period("M"))["label_up"].mean().items()
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quarterly walk-forward evaluation for fixed daily stock Top15."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_FEATURE_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument("--seed", type=int, default=149)
    parser.add_argument("--training-years", type=int, default=0)
    parser.add_argument("--half-life-years", type=float, default=0.0)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = pd.read_parquet(args.feature_cache)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[data["label_up"].notna()].sort_values(["date", "code"], kind="stable")
    columns = [
        value
        for value in args.feature_columns.read_text(encoding="utf-8").splitlines()
        if value in data.columns
    ]
    scored_parts = []
    period_reports = []
    for index, (start, end, train_end) in enumerate(_periods(args.year), start=1):
        evaluation = data[data["date"].between(start, end)].copy()
        if evaluation.empty:
            continue
        train_start = None
        if args.training_years:
            train_start = (
                pd.Timestamp(train_end) - pd.DateOffset(years=int(args.training_years))
            ) + pd.Timedelta(days=1)
        training = data[data["date"].le(train_end)].copy()
        if train_start is not None:
            training = training[training["date"].ge(train_start)]
        weights = None
        if args.half_life_years > 0:
            age_years = (
                pd.Timestamp(train_end) - training["date"]
            ).dt.days.to_numpy() / 365.25
            weights = np.power(0.5, age_years / float(args.half_life_years))
        group = training.groupby("date", sort=False).size().to_numpy()
        dataset = lgb.Dataset(
            training[columns],
            label=training["label_up"].astype(int),
            weight=weights,
            group=group,
            params={
                "data_random_seed": args.seed,
                "feature_pre_filter": False,
            },
            free_raw_data=True,
        )
        print(
            f"[{index}/4] train through {train_end}: rows={len(training)}, "
            f"evaluate={start}..{end}",
            flush=True,
        )
        model = lgb.train(
            _model_parameters(args.seed),
            dataset,
            num_boost_round=int(args.iterations),
            callbacks=[lgb.log_evaluation(0)],
        )
        evaluation["score"] = model.predict(evaluation[columns])
        evaluation["train_end"] = train_end
        scored_parts.append(evaluation.loc[:, ["date", "code", "label_up", "score", "train_end"]])
        period_reports.append(
            {
                "start": start,
                "end": end,
                "train_start": str(training["date"].min().date()),
                "train_end": train_end,
                **_score_metrics(evaluation),
            }
        )
    scored = pd.concat(scored_parts, ignore_index=True)
    metrics = _score_metrics(scored)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "quarterly_walk_forward_fixed_daily_top15_precision",
        "year": args.year,
        "iterations": args.iterations,
        "seed": args.seed,
        "training_years": args.training_years,
        "half_life_years": args.half_life_years,
        "feature_count": len(columns),
        "overall": metrics,
        "periods": period_reports,
    }
    args.predictions_path.parent.mkdir(parents=True, exist_ok=True)
    scored.to_parquet(args.predictions_path, index=False)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
