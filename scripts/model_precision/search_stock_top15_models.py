from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEATURE_CACHE = (
    ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
)
DEFAULT_FEATURE_COLUMNS = (
    ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v5_alpha.txt"
)
DEFAULT_REPORT = (
    ROOT / "outputs" / "model_precision" / "stock_top15_model_search.json"
)
DEFAULT_PREDICTIONS = (
    ROOT / "data" / "model_precision" / "stock_top15_search_validation_predictions.parquet"
)


def _top15_precision(
    dates: pd.Series,
    codes: pd.Series,
    labels: np.ndarray,
    scores: np.ndarray,
) -> float:
    scored = pd.DataFrame(
        {
            "date": dates.to_numpy(),
            "code": codes.to_numpy(),
            "label": labels,
            "score": scores,
        }
    )
    top = (
        scored.sort_values(
            ["date", "score", "code"],
            ascending=[True, False, True],
            kind="stable",
        )
        .groupby("date", sort=False)
        .head(15)
    )
    counts = top.groupby("date", sort=False).size()
    if counts.empty or not counts.eq(15).all():
        raise RuntimeError("evaluation must contain exactly 15 selections per day")
    return float(top["label"].mean())


def _feature_sets(columns: list[str]) -> dict[str, list[str]]:
    v3_path = (
        ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
    )
    v3 = [
        value
        for value in v3_path.read_text(encoding="utf-8").splitlines()
        if value in columns
    ]
    date_constant_prefixes = ("market_", "kronos_daily_", "month", "weekday")
    no_market = [
        value for value in columns if not value.startswith(date_constant_prefixes)
    ]
    rank_focused_prefixes = (
        "alpha_",
        "basic_",
        "cross_pct_",
        "existing_rank_pct",
        "flow_",
        "industry_",
        "is_",
        "kronos_",
        "margin_",
        "prior_",
        "relative_",
        "stock_",
        "tech_",
    )
    rank_focused = [
        value for value in columns if value.startswith(rank_focused_prefixes)
    ]
    daily_cross = list(
        dict.fromkeys([*v3, *[value for value in columns if value.startswith("cross_all_pct_")]])
    )
    alpha_cross = list(
        dict.fromkeys(
            [
                *v3,
                *[
                    value
                    for value in columns
                    if value.startswith("cross_all_pct_alpha_")
                ],
            ]
        )
    )
    industry_cross = list(
        dict.fromkeys([*v3, *[value for value in columns if value.startswith("industry_pct_")]])
    )
    event_core = list(
        dict.fromkeys(
            [
                *v3,
                *[
                    value
                    for value in columns
                    if value.startswith(("event_", "listing_age_"))
                ],
            ]
        )
    )
    alpha_complete = list(
        dict.fromkeys(
            [
                *v3,
                *[value for value in columns if value.startswith("alpha_")],
                *[value for value in columns if value.startswith("listing_age_")],
            ]
        )
    )
    event_alpha = list(
        dict.fromkeys(
            [
                *event_core,
                *[value for value in columns if value.startswith("alpha_")],
            ]
        )
    )
    return {
        "v3": v3,
        "all": columns,
        "no_market": no_market,
        "rank_focused": rank_focused,
        "daily_cross": daily_cross,
        "alpha_cross": alpha_cross,
        "industry_cross": industry_cross,
        "event_core": event_core,
        "alpha_complete": alpha_complete,
        "event_alpha": event_alpha,
    }


def _configs() -> list[dict[str, Any]]:
    return [
        {"name": "xendcg_v3_d4", "features": "v3", "objective": "rank_xendcg", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 11},
        {"name": "xendcg_v3_d6", "features": "v3", "objective": "rank_xendcg", "num_leaves": 31, "max_depth": 6, "min_child_samples": 120, "feature_fraction": 0.70, "seed": 23},
        {"name": "xendcg_v3_leaf63", "features": "v3", "objective": "rank_xendcg", "num_leaves": 63, "max_depth": 8, "min_child_samples": 180, "feature_fraction": 0.65, "seed": 37},
        {"name": "lambda_v3_d4", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 41},
        {"name": "lambda_v3_d6", "features": "v3", "objective": "lambdarank", "num_leaves": 31, "max_depth": 6, "min_child_samples": 180, "feature_fraction": 0.70, "seed": 53},
        {"name": "lambda_v3_d3_t15", "features": "v3", "objective": "lambdarank", "num_leaves": 7, "max_depth": 3, "min_child_samples": 160, "feature_fraction": 0.75, "truncation": 15, "seed": 131},
        {"name": "lambda_v3_d4_t15", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 160, "feature_fraction": 0.65, "truncation": 15, "seed": 137},
        {"name": "lambda_v3_d4_t30", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 240, "feature_fraction": 0.55, "truncation": 30, "seed": 139},
        {"name": "lambda_v3_d4_t50", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 149},
        {"name": "lambda_v3_seed11", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 11},
        {"name": "lambda_v3_seed23", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 23},
        {"name": "lambda_v3_seed61", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 61},
        {"name": "lambda_v3_seed83", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 83},
        {"name": "lambda_v3_seed101", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 120, "feature_fraction": 0.75, "seed": 101},
        {"name": "lambda_t50_seed11", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 11},
        {"name": "lambda_t50_seed23", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 23},
        {"name": "lambda_t50_seed41", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 41},
        {"name": "lambda_t50_seed61", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 61},
        {"name": "lambda_t50_seed83", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 83},
        {"name": "lambda_t50_seed101", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_all_seed101", "features": "all", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_dailycross", "features": "daily_cross", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_alphacross", "features": "alpha_cross", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_industrycross", "features": "industry_cross", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_nomarket", "features": "no_market", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_decay2", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "half_life": 2.0, "seed": 101},
        {"name": "lambda_t50_decay3", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "half_life": 3.0, "seed": 101},
        {"name": "lambda_t50_decay5", "features": "v3", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "half_life": 5.0, "seed": 101},
        {"name": "lambda_t50_event", "features": "event_core", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_alpha158", "features": "alpha_complete", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "lambda_t50_event_alpha", "features": "event_alpha", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 80, "feature_fraction": 0.90, "truncation": 50, "seed": 101},
        {"name": "xendcg_all_d4", "features": "all", "objective": "rank_xendcg", "num_leaves": 15, "max_depth": 4, "min_child_samples": 150, "feature_fraction": 0.65, "seed": 61},
        {"name": "xendcg_all_d6", "features": "all", "objective": "rank_xendcg", "num_leaves": 31, "max_depth": 6, "min_child_samples": 180, "feature_fraction": 0.60, "seed": 71},
        {"name": "xendcg_all_leaf63", "features": "all", "objective": "rank_xendcg", "num_leaves": 63, "max_depth": 8, "min_child_samples": 240, "feature_fraction": 0.55, "seed": 83},
        {"name": "lambda_all_d4", "features": "all", "objective": "lambdarank", "num_leaves": 15, "max_depth": 4, "min_child_samples": 150, "feature_fraction": 0.65, "seed": 97},
        {"name": "xendcg_nomarket_d4", "features": "no_market", "objective": "rank_xendcg", "num_leaves": 15, "max_depth": 4, "min_child_samples": 150, "feature_fraction": 0.70, "seed": 101},
        {"name": "xendcg_nomarket_d6", "features": "no_market", "objective": "rank_xendcg", "num_leaves": 31, "max_depth": 6, "min_child_samples": 200, "feature_fraction": 0.65, "seed": 113},
        {"name": "xendcg_rankfocused", "features": "rank_focused", "objective": "rank_xendcg", "num_leaves": 31, "max_depth": 6, "min_child_samples": 180, "feature_fraction": 0.65, "seed": 127},
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search causal LightGBM rankers for fixed daily Top15 precision."
    )
    parser.add_argument("--feature-cache", type=Path, default=DEFAULT_FEATURE_CACHE)
    parser.add_argument("--feature-columns", type=Path, default=DEFAULT_FEATURE_COLUMNS)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--predictions-path", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--max-iterations", type=int, default=480)
    parser.add_argument(
        "--models",
        nargs="*",
        default=None,
        help="Optional model names to run; defaults to the full search grid.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = pd.read_parquet(args.feature_cache)
    columns = [
        value
        for value in args.feature_columns.read_text(encoding="utf-8").splitlines()
        if value in data.columns
    ]
    data = data[data["label_up"].notna()].sort_values(
        ["date", "code"], kind="stable"
    )
    train = data[data["date"].le("2024-12-31")].copy()
    validation = data[
        data["date"].gt("2024-12-31") & data["date"].le("2025-12-31")
    ].copy()
    train_group = train.groupby("date", sort=False).size().to_numpy()
    feature_sets = _feature_sets(columns)
    checkpoints = sorted(
        set(range(40, int(args.max_iterations) + 1, 40)) | {int(args.max_iterations)}
    )
    configs = _configs()
    if args.models:
        wanted = set(args.models)
        configs = [config for config in configs if config["name"] in wanted]
        missing = wanted.difference(config["name"] for config in configs)
        if missing:
            raise ValueError(f"unknown model names: {sorted(missing)}")
    results: list[dict[str, Any]] = []
    prediction_frame = validation.loc[:, ["date", "code", "label_up", "pred_return"]].copy()
    labels = validation["label_up"].astype(int).to_numpy()
    for index, config in enumerate(configs, start=1):
        selected = feature_sets[config["features"]]
        print(
            f"[{index}/{len(configs)}] training {config['name']} "
            f"with {len(selected)} features",
            flush=True,
        )
        parameters = {
            "objective": config["objective"],
            "metric": "ndcg",
            "ndcg_eval_at": [15],
            "learning_rate": 0.025,
            "num_leaves": config["num_leaves"],
            "max_depth": config["max_depth"],
            "min_child_samples": config["min_child_samples"],
            "feature_fraction": config["feature_fraction"],
            "bagging_fraction": 0.85,
            "bagging_freq": 1,
            "lambda_l1": 0.3,
            "lambda_l2": 2.0,
            "seed": config["seed"],
            "feature_fraction_seed": config["seed"],
            "bagging_seed": config["seed"],
            "feature_pre_filter": False,
            "data_random_seed": config["seed"],
            "verbosity": -1,
            "num_threads": -1,
        }
        if config.get("truncation"):
            parameters["lambdarank_truncation_level"] = int(config["truncation"])
        dataset = lgb.Dataset(
            train[selected],
            label=train["label_up"].astype(int),
            weight=(
                np.power(
                    0.5,
                    (
                        pd.Timestamp("2024-12-31") - train["date"]
                    ).dt.days.to_numpy()
                    / 365.25
                    / float(config["half_life"]),
                )
                if config.get("half_life")
                else None
            ),
            group=train_group,
            params={
                "data_random_seed": config["seed"],
                "feature_pre_filter": False,
            },
            free_raw_data=False,
        )
        booster = lgb.train(
            parameters,
            dataset,
            num_boost_round=int(args.max_iterations),
            callbacks=[lgb.log_evaluation(0)],
        )
        curve = []
        best_precision = -1.0
        best_iteration = 0
        best_scores: np.ndarray | None = None
        for iteration in checkpoints:
            scores = booster.predict(validation[selected], num_iteration=iteration)
            precision = _top15_precision(
                validation["date"], validation["code"], labels, scores
            )
            curve.append({"iteration": iteration, "precision": precision})
            if precision > best_precision:
                best_precision = precision
                best_iteration = iteration
                best_scores = scores
        assert best_scores is not None
        prediction_frame[config["name"]] = best_scores.astype("float32")
        row = {
            **config,
            "feature_count": len(selected),
            "best_iteration": best_iteration,
            "validation_precision": best_precision,
            "curve": curve,
            "top_feature_importance": [
                {"feature": feature, "gain": float(gain)}
                for feature, gain in sorted(
                    zip(
                        selected,
                        booster.feature_importance(
                            importance_type="gain", iteration=best_iteration
                        ),
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )[:80]
            ],
        }
        results.append(row)
        print(
            f"[{index}/{len(configs)}] {config['name']}: "
            f"precision={best_precision:.6f}, iteration={best_iteration}",
            flush=True,
        )

    score_columns = [config["name"] for config in configs]
    ensemble_rows = []
    ordered = sorted(results, key=lambda row: row["validation_precision"], reverse=True)
    for count in sorted({value for value in (2, 3, 5, 8, 12) if value <= len(ordered)}):
        names = [row["name"] for row in ordered[:count]]
        ranks = prediction_frame.groupby("date", sort=False)[names].rank(pct=True)
        scores = ranks.mean(axis=1).to_numpy()
        precision = _top15_precision(
            validation["date"], validation["code"], labels, scores
        )
        ensemble_rows.append(
            {"count": count, "members": names, "validation_precision": precision}
        )
    prediction_frame[score_columns] = prediction_frame[score_columns].astype("float32")
    args.predictions_path.parent.mkdir(parents=True, exist_ok=True)
    prediction_frame.to_parquet(args.predictions_path, index=False)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "fixed_daily_top15_next_day_up_precision",
        "selection_count_per_day": 15,
        "training_end": "2024-12-31",
        "validation_start": "2025-01-01",
        "validation_end": "2025-12-31",
        "baseline_pred_return_precision": _top15_precision(
            validation["date"],
            validation["code"],
            labels,
            validation["pred_return"].to_numpy(),
        ),
        "models": results,
        "ensembles": ensemble_rows,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.report_path.with_suffix(args.report_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(args.report_path)
    print(json.dumps({"best_models": ordered[:5], "ensembles": ensemble_rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
