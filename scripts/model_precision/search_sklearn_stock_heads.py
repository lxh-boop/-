from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "model_precision" / "stock_direction_features_v5_alpha.parquet"
FEATURE_REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_feature_subset_search.json"
REPORT = ROOT / "outputs" / "model_precision" / "stock_top15_sklearn_heads.json"
PREDICTIONS = ROOT / "data" / "model_precision" / "stock_top15_sklearn_validation.parquet"


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


def main() -> int:
    data = pd.read_parquet(CACHE)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data[data["label_up"].notna()].sort_values(["date", "code"], kind="stable")
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding="utf-8"))
    columns = next(
        row["features"]
        for row in feature_report["results"]
        if int(row["feature_count"]) == 80
    )
    training = data[data["date"].le("2024-12-31")]
    validation = data[data["date"].between("2025-01-01", "2025-12-31")].copy()
    x_train = training[columns].to_numpy(dtype=np.float32, copy=True)
    y_train = training["label_up"].astype(int).to_numpy()
    x_validation = validation[columns].to_numpy(dtype=np.float32, copy=True)
    models = {
        "extra_trees": make_pipeline(
            SimpleImputer(strategy="median"),
            ExtraTreesClassifier(
                n_estimators=300,
                max_depth=12,
                min_samples_leaf=80,
                max_features=0.70,
                class_weight="balanced",
                random_state=61,
                n_jobs=-1,
            ),
        ),
        "hist_gradient": HistGradientBoostingClassifier(
            learning_rate=0.06,
            max_iter=220,
            max_leaf_nodes=15,
            min_samples_leaf=100,
            l2_regularization=2.0,
            early_stopping=False,
            random_state=67,
        ),
        "random_forest": make_pipeline(
            SimpleImputer(strategy="median"),
            RandomForestClassifier(
                n_estimators=180,
                max_depth=10,
                min_samples_leaf=100,
                max_features=0.50,
                class_weight="balanced_subsample",
                random_state=71,
                n_jobs=-1,
            ),
        ),
        "linear_logistic": make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            SGDClassifier(
                loss="log_loss",
                penalty="elasticnet",
                alpha=0.0003,
                l1_ratio=0.05,
                max_iter=80,
                tol=1e-4,
                class_weight="balanced",
                random_state=73,
                average=True,
            ),
        ),
    }
    prediction_frame = validation.loc[:, ["date", "code", "label_up", "pred_return"]].copy()
    results = []
    for index, (name, model) in enumerate(models.items(), start=1):
        print(f"[{index}/{len(models)}] training {name}", flush=True)
        model.fit(x_train, y_train)
        if hasattr(model, "predict_proba"):
            scores = model.predict_proba(x_validation)[:, 1]
        else:
            scores = model.decision_function(x_validation)
        prediction_frame[name] = np.asarray(scores, dtype="float32")
        metrics = _metrics(validation, scores)
        results.append({"model": name, **metrics})
        print(f"{name}: precision={metrics['precision']:.6f}", flush=True)
    score_columns = list(models)
    ranks = prediction_frame.groupby("date", sort=False)[score_columns].rank(pct=True)
    ensembles = []
    ordered = [row["model"] for row in sorted(results, key=lambda row: row["precision"], reverse=True)]
    for count in range(2, len(ordered) + 1):
        metrics = _metrics(validation, ranks[ordered[:count]].mean(axis=1).to_numpy())
        ensembles.append({"models": ordered[:count], **metrics})
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "objective": "fixed_daily_top15_classification_heads",
        "feature_count": len(columns),
        "models": results,
        "ensembles": ensembles,
        "accepted": bool(
            max([row["precision"] for row in results + ensembles], default=0.0) >= 0.55
        ),
    }
    PREDICTIONS.parent.mkdir(parents=True, exist_ok=True)
    prediction_frame.to_parquet(PREDICTIONS, index=False)
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
