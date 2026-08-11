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
DEFAULT_REPORT = (
    ROOT / "outputs" / "model_precision" / "stock_top15_feature_subset_search.json"
)
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_feature_subset_predictions.parquet"
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


def _train(
    training: pd.DataFrame,
    columns: list[str],
    *,
    seed: int,
    iterations: int,
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


def _precision(validation: pd.DataFrame, scores: np.ndarray) -> tuple[float, float, float]:
    top = (
        validation.assign(_score=scores)
        .sort_values(
            ["date", "_score", "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    if not top.groupby("date").size().eq(15).all():
        raise RuntimeError("each evaluation day must contain exactly 15 selections")
    first = top[top["date"].lt("2025-07-01")]["label_up"].mean()
    second = top[top["date"].ge("2025-07-01")]["label_up"].mean()
    return float(top["label_up"].mean()), float(first), float(second)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Training-only gain feature selection for fixed daily Top15."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_COLUMNS)
    parser.add_argument("--seed", type=int, default=101)
    parser.add_argument("--max-iterations", type=int, default=200)
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
    training = data[data["date"].le("2024-12-31")].copy()
    validation = data[
        data["date"].gt("2024-12-31") & data["date"].le("2025-12-31")
    ].copy()
    print(f"training importance model with {len(columns)} features", flush=True)
    importance_model = _train(
        training, columns, seed=args.seed, iterations=min(120, args.max_iterations)
    )
    gains = importance_model.feature_importance(importance_type="gain")
    ordered = [
        feature
        for feature, _ in sorted(
            zip(columns, gains), key=lambda item: item[1], reverse=True
        )
    ]
    counts = sorted(
        {
            value
            for value in (20, 40, 60, 80, 120, 160, len(columns))
            if value <= len(columns)
        }
    )
    checkpoints = sorted(
        set(range(40, args.max_iterations + 1, 40)) | {args.max_iterations}
    )
    predictions = validation.loc[:, ["date", "code", "label_up", "pred_return"]].copy()
    results = []
    for index, count in enumerate(counts, start=1):
        selected = ordered[:count]
        print(f"[{index}/{len(counts)}] training top {count} features", flush=True)
        model = _train(
            training,
            selected,
            seed=args.seed,
            iterations=args.max_iterations,
        )
        curve = []
        best = (-1.0, 0.0, 0.0, 0, None)
        for iteration in checkpoints:
            scores = model.predict(validation[selected], num_iteration=iteration)
            overall, first, second = _precision(validation, scores)
            curve.append(
                {
                    "iteration": iteration,
                    "precision": overall,
                    "first_half": first,
                    "second_half": second,
                }
            )
            if overall > best[0]:
                best = (overall, first, second, iteration, scores)
        predictions[f"top_{count}"] = np.asarray(best[4], dtype="float32")
        results.append(
            {
                "feature_count": count,
                "best_iteration": best[3],
                "validation_precision": best[0],
                "first_half": best[1],
                "second_half": best[2],
                "features": selected,
                "curve": curve,
            }
        )
        print(
            f"top {count}: precision={best[0]:.6f}, iteration={best[3]}",
            flush=True,
        )
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "fixed_daily_top15_training_only_gain_feature_selection",
        "seed": args.seed,
        "results": results,
    }
    args.predictions_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(args.predictions_path, index=False)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.report_path)
    print(json.dumps(sorted(results, key=lambda row: row["validation_precision"], reverse=True)[:3], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
