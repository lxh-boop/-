from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
FEATURE_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_feature_subset_search.json"
BASE_COLUMNS = ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
VALIDATION_BASE = ROOT / "data" / "model_precision" / "stock_top15_search_seeds.parquet"
HOLDOUT_BASE = ROOT / "data" / "model_precision" / "stock_top15_candidate_ensemble_holdout.parquet"
REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_oof_meta_head.json"
PREDICTIONS = ROOT / "data" / "model_precision" / "stock_top15_oof_meta_holdout.parquet"


def _base_parameters(seed: int) -> dict[str, object]:
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


def _meta_parameters(objective: str, seed: int) -> dict[str, object]:
    parameters = {
        "objective": objective,
        "learning_rate": 0.03,
        "num_leaves": 7,
        "max_depth": 3,
        "min_child_samples": 100,
        "feature_fraction": 0.85,
        "bagging_fraction": 0.85,
        "bagging_freq": 1,
        "lambda_l1": 0.5,
        "lambda_l2": 3.0,
        "seed": seed,
        "feature_fraction_seed": seed,
        "bagging_seed": seed,
        "data_random_seed": seed,
        "feature_pre_filter": False,
        "verbosity": -1,
        "num_threads": -1,
    }
    if objective in {"lambdarank", "rank_xendcg"}:
        parameters.update(
            {
                "metric": "ndcg",
                "ndcg_eval_at": [15],
                "lambdarank_truncation_level": 50,
            }
        )
    else:
        parameters["metric"] = "binary_logloss"
    return parameters


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
        "first_half": float(top[top["date"].dt.month.le(6)]["label_up"].mean()),
        "second_half": float(top[top["date"].dt.month.gt(6)]["label_up"].mean()),
    }


def _train_base(
    training: pd.DataFrame,
    columns: list[str],
    *,
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
        _base_parameters(seed),
        dataset,
        num_boost_round=120,
        callbacks=[lgb.log_evaluation(0)],
    )


def _attach_base_rank(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["oof_base_rank"] = result.groupby("date", sort=False)["oof_base_score"].rank(
        pct=True, method="average"
    )
    return result


def _train_meta(
    training: pd.DataFrame,
    columns: list[str],
    *,
    objective: str,
    iterations: int,
    seed: int,
) -> lgb.Booster:
    group = None
    if objective in {"lambdarank", "rank_xendcg"}:
        group = training.groupby("date", sort=False).size().to_numpy()
    dataset = lgb.Dataset(
        training[columns],
        label=training["label_up"].astype(int),
        group=group,
        params={"data_random_seed": seed, "feature_pre_filter": False},
        free_raw_data=True,
    )
    return lgb.train(
        _meta_parameters(objective, seed),
        dataset,
        num_boost_round=iterations,
        callbacks=[lgb.log_evaluation(0)],
    )


def main() -> int:
    data = pd.read_parquet(CACHE)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[data["label_up"].notna()].sort_values(["date", "code"], kind="stable")
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding="utf-8"))
    base_columns = [
        value
        for value in BASE_COLUMNS.read_text(encoding="utf-8").splitlines()
        if value in data.columns
    ]
    meta_raw_columns = next(
        row["features"]
        for row in feature_report["results"]
        if int(row["feature_count"]) == 20
    )
    oof_parts = []
    for index, year in enumerate((2022, 2023, 2024), start=1):
        training = data[data["date"].lt(f"{year}-01-01")].copy()
        evaluation = data[data["date"].between(f"{year}-01-01", f"{year}-12-31")].copy()
        print(f"[base {index}/3] train through {year-1}, score {year}", flush=True)
        model = _train_base(training, base_columns, seed=101)
        evaluation["oof_base_score"] = model.predict(evaluation[base_columns]).astype("float32")
        oof_parts.append(evaluation)
    meta_training = _attach_base_rank(pd.concat(oof_parts, ignore_index=True))

    validation_scores = pd.read_parquet(VALIDATION_BASE)[
        ["date", "code", "lambda_t50_seed101"]
    ].rename(columns={"lambda_t50_seed101": "oof_base_score"})
    validation_scores["date"] = pd.to_datetime(validation_scores["date"], errors="coerce")
    validation = data[data["date"].between("2025-01-01", "2025-12-31")].merge(
        validation_scores, on=["date", "code"], how="inner"
    )
    validation = _attach_base_rank(validation.sort_values(["date", "code"], kind="stable"))
    meta_columns = ["oof_base_score", "oof_base_rank", *meta_raw_columns]
    candidates = []
    validation_predictions = {}
    for objective in ("lambdarank", "rank_xendcg", "binary"):
        print(f"training meta objective={objective}", flush=True)
        model = _train_meta(
            meta_training,
            meta_columns,
            objective=objective,
            iterations=200,
            seed=211,
        )
        for iteration in (40, 80, 120, 160, 200):
            scores = model.predict(validation[meta_columns], num_iteration=iteration)
            metrics = _metrics(validation, scores)
            key = f"{objective}_{iteration}"
            validation_predictions[key] = scores.astype("float32")
            candidates.append(
                {"objective": objective, "iterations": iteration, **metrics}
            )
    selected = max(
        candidates,
        key=lambda row: (row["precision"], row["second_half"]),
    )
    print(f"selected on 2025: {selected}", flush=True)

    validation_for_meta = validation.copy()
    meta_final_training = pd.concat(
        [meta_training, validation_for_meta], ignore_index=True
    ).sort_values(["date", "code"], kind="stable")
    final_meta = _train_meta(
        meta_final_training,
        meta_columns,
        objective=str(selected["objective"]),
        iterations=int(selected["iterations"]),
        seed=211,
    )
    holdout_scores = pd.read_parquet(HOLDOUT_BASE)[
        ["date", "code", "seed101"]
    ].rename(columns={"seed101": "oof_base_score"})
    holdout_scores["date"] = pd.to_datetime(holdout_scores["date"], errors="coerce")
    holdout = data[data["date"].gt("2025-12-31")].merge(
        holdout_scores, on=["date", "code"], how="inner"
    )
    holdout = _attach_base_rank(holdout.sort_values(["date", "code"], kind="stable"))
    holdout["meta_score"] = final_meta.predict(holdout[meta_columns]).astype("float32")
    holdout_metrics = _metrics(holdout, holdout["meta_score"].to_numpy())
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "oof_base_prediction_second_stage_fixed_daily_top15",
        "meta_training_years": [2022, 2023, 2024],
        "meta_feature_count": len(meta_columns),
        "validation_candidates": candidates,
        "validation_selected": selected,
        "holdout": holdout_metrics,
        "accepted": bool(
            selected["precision"] >= 0.55 and holdout_metrics["precision"] >= 0.55
        ),
    }
    PREDICTIONS.parent.mkdir(parents=True, exist_ok=True)
    holdout.loc[:, ["date", "code", "label_up", "oof_base_score", "oof_base_rank", "meta_score"]].to_parquet(
        PREDICTIONS, index=False
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(REPORT.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(REPORT)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
