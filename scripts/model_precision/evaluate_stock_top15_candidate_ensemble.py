from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
COLUMNS = ROOT / "data" / "model_precision" / "stock_direction_feature_columns_v3.txt"
FEATURE_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_feature_subset_search.json"
OUTPUT = ROOT / "data" / "model_precision" / "stock_top15_candidate_ensemble_holdout.parquet"
REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_candidate_ensemble_holdout.json"


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


def _metrics(frame: pd.DataFrame, score_column: str) -> dict[str, object]:
    top = (
        frame.sort_values(
            ["date", score_column, "code"],
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
        "monthly": {
            str(month): float(value)
            for month, value in top.groupby(top["date"].dt.to_period("M"))["label_up"].mean().items()
        },
    }


def main() -> int:
    data = pd.read_parquet(CACHE)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[data["label_up"].notna()].sort_values(["date", "code"], kind="stable")
    base_columns = [
        value
        for value in COLUMNS.read_text(encoding="utf-8").splitlines()
        if value in data.columns
    ]
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding="utf-8"))
    reordered = next(
        row["features"]
        for row in feature_report["results"]
        if int(row["feature_count"]) == len(base_columns)
    )
    training = data[data["date"].le("2025-12-31")].copy()
    holdout = data[data["date"].gt("2025-12-31")].copy()
    configurations = [
        ("seed101", base_columns, 101, 120, 0.1647813272195915),
        ("gain_order", reordered, 101, 160, 0.673005517829718),
        ("seed149", base_columns, 149, 120, 0.02817242825489619),
        ("seed23", base_columns, 23, 160, 0.13404072669579434),
    ]
    for index, (name, columns, seed, iterations, _) in enumerate(configurations, start=1):
        print(f"[{index}/{len(configurations)}] training {name}", flush=True)
        dataset = lgb.Dataset(
            training[columns],
            label=training["label_up"].astype(int),
            group=training.groupby("date", sort=False).size().to_numpy(),
            params={"data_random_seed": seed, "feature_pre_filter": False},
            free_raw_data=True,
        )
        model = lgb.train(
            _parameters(seed),
            dataset,
            num_boost_round=iterations,
            callbacks=[lgb.log_evaluation(0)],
        )
        holdout[name] = model.predict(holdout[columns]).astype("float32")
    score_columns = [item[0] for item in configurations]
    weights = np.asarray([item[4] for item in configurations])
    ranks = holdout.groupby("date", sort=False)[score_columns].rank(pct=True)
    holdout["ensemble_score"] = ranks.mul(weights, axis=1).sum(axis=1)
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "fixed_daily_top15_next_day_up_precision",
        "selection_count_per_day": 15,
        "validation_precision_used_for_selection": 0.549519890260631,
        "validation_correct": 2003,
        "validation_signals": 3645,
        "weights": {
            name: weight for name, _, _, _, weight in configurations
        },
        "holdout": _metrics(holdout, "ensemble_score"),
        "accepted": False,
        "acceptance_reason": "validation precision is below 0.55",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    holdout.loc[:, ["date", "code", "label_up", *score_columns, "ensemble_score"]].to_parquet(
        OUTPUT, index=False
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
