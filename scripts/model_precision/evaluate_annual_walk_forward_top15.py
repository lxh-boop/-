from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
)
DEFAULT_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
)
DEFAULT_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_annual_walk_forward.json"
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_annual_walk_forward.parquet"
)


def _parameters(seed: int) -> dict[str, object]:
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


def _metrics(frame: pd.DataFrame) -> dict[str, object]:
    top = (
        frame.sort_values(
            ["date", "score", "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    counts = top.groupby("date").size()
    return {
        "days": int(top["date"].nunique()),
        "signals": int(len(top)),
        "correct": int(top["label_up"].sum()),
        "precision": float(top["label_up"].mean()),
        "all_days_have_15": bool(not counts.empty and counts.eq(15).all()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Annual expanding walk-forward evaluation for fixed daily Top15."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_COLUMNS)
    parser.add_argument("--start-year", type=int, default=2022)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--iterations", type=int, default=120)
    parser.add_argument("--seed", type=int, default=101)
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
    yearly = []
    for index, year in enumerate(range(args.start_year, args.end_year + 1), start=1):
        training = data[data["date"].lt(f"{year}-01-01")].copy()
        evaluation = data[data["date"].between(f"{year}-01-01", f"{year}-12-31")].copy()
        if training.empty or evaluation.empty:
            continue
        print(
            f"[{index}/{args.end_year-args.start_year+1}] train through {year-1}, "
            f"evaluate {year}",
            flush=True,
        )
        dataset = lgb.Dataset(
            training[columns],
            label=training["label_up"].astype(int),
            group=training.groupby("date", sort=False).size().to_numpy(),
            params={"data_random_seed": args.seed, "feature_pre_filter": False},
            free_raw_data=True,
        )
        model = lgb.train(
            _parameters(args.seed),
            dataset,
            num_boost_round=args.iterations,
            callbacks=[lgb.log_evaluation(0)],
        )
        evaluation["score"] = model.predict(evaluation[columns]).astype("float32")
        scored_parts.append(evaluation.loc[:, ["date", "code", "label_up", "score"]])
        yearly.append({"year": year, **_metrics(evaluation)})
    scored = pd.concat(scored_parts, ignore_index=True)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "annual_expanding_walk_forward_fixed_daily_top15_precision",
        "iterations": args.iterations,
        "seed": args.seed,
        "feature_count": len(columns),
        "overall": _metrics(scored),
        "years": yearly,
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
