from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

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
DEFAULT_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_regime_ensemble.json"
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_regime_ensemble_holdout.parquet"
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


def _train_year(
    training: pd.DataFrame,
    columns: list[str],
    *,
    iterations: int,
    seed: int,
) -> lgb.Booster:
    dataset = lgb.Dataset(
        training[columns],
        label=training["label_up"].astype(int),
        group=training.groupby("date", sort=False).size().to_numpy(),
        params={"data_random_seed": seed, "feature_pre_filter": False},
        free_raw_data=True,
    )
    return lgb.train(
        _parameters(seed),
        dataset,
        num_boost_round=iterations,
        callbacks=[lgb.log_evaluation(0)],
    )


def _metrics(frame: pd.DataFrame, scores: np.ndarray) -> dict[str, object]:
    top = (
        frame.assign(_score=scores)
        .sort_values(
            ["date", "_score", "code"],
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
        "first_half": float(
            top[top["date"].dt.month.le(6)]["label_up"].mean()
        ),
        "second_half": float(
            top[top["date"].dt.month.gt(6)]["label_up"].mean()
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ensemble one model per historical regime year for fixed Top15."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_COLUMNS)
    parser.add_argument("--max-iterations", type=int, default=160)
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
    validation = data[data["date"].between("2025-01-01", "2025-12-31")].copy()
    checkpoints = list(range(40, args.max_iterations + 1, 40))
    validation_predictions: dict[tuple[int, int], np.ndarray] = {}
    training_years = list(range(2019, 2025))
    for index, year in enumerate(training_years, start=1):
        training = data[data["date"].dt.year.eq(year)].copy()
        print(f"[{index}/{len(training_years)}] train regime year {year}", flush=True)
        model = _train_year(
            training, columns, iterations=args.max_iterations, seed=args.seed + year
        )
        for iteration in checkpoints:
            validation_predictions[(year, iteration)] = model.predict(
                validation[columns], num_iteration=iteration
            ).astype("float32")
    candidates = []
    for iteration in checkpoints:
        for count in range(2, len(training_years) + 1):
            years = training_years[-count:]
            matrix = pd.DataFrame(
                {
                    str(year): validation_predictions[(year, iteration)]
                    for year in years
                }
            )
            ranks = matrix.groupby(validation["date"].reset_index(drop=True)).rank(pct=True)
            scores = ranks.mean(axis=1).to_numpy()
            candidates.append(
                {
                    "iterations": iteration,
                    "regime_year_count": count,
                    "regime_years": years,
                    **_metrics(validation, scores),
                }
            )
    selected = max(
        candidates,
        key=lambda row: (row["precision"], row["second_half"], -row["regime_year_count"]),
    )
    print(f"selected on 2025: {selected}", flush=True)

    holdout = data[data["date"].gt("2025-12-31")].copy()
    final_years = list(
        range(2026 - int(selected["regime_year_count"]), 2026)
    )
    final_scores = {}
    for index, year in enumerate(final_years, start=1):
        training = data[data["date"].dt.year.eq(year)].copy()
        print(f"[holdout {index}/{len(final_years)}] train regime year {year}", flush=True)
        model = _train_year(
            training,
            columns,
            iterations=int(selected["iterations"]),
            seed=args.seed + year,
        )
        final_scores[str(year)] = model.predict(holdout[columns]).astype("float32")
    score_frame = pd.DataFrame(final_scores)
    holdout_ranks = score_frame.groupby(holdout["date"].reset_index(drop=True)).rank(pct=True)
    holdout["ensemble_score"] = holdout_ranks.mean(axis=1).to_numpy()
    holdout_metrics = _metrics(holdout, holdout["ensemble_score"].to_numpy())
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "year_regime_ensemble_fixed_daily_top15_precision",
        "feature_count": len(columns),
        "validation_selected": selected,
        "validation_candidates": candidates,
        "holdout_regime_years": final_years,
        "holdout": holdout_metrics,
        "accepted": bool(
            selected["precision"] >= 0.55 and holdout_metrics["precision"] >= 0.55
        ),
    }
    args.predictions_path.parent.mkdir(parents=True, exist_ok=True)
    holdout.loc[:, ["date", "code", "label_up", "ensemble_score"]].to_parquet(
        args.predictions_path, index=False
    )
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
