from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from config import MODEL_PRED_COL, OUTPUT_DIR


REPORT_PATH = Path(OUTPUT_DIR) / "model_compare_report.csv"


MODEL_PREDICTION_FILES = [
    {
        "model_backend": "torch_mlp",
        "path": Path(OUTPUT_DIR) / "test_predictions.csv",
        "metrics_path": Path("models") / "torch_mlp" / "latest" / "metrics.json",
    },
    {
        "model_backend": "lightgbm",
        "path": Path(OUTPUT_DIR) / "test_predictions_lightgbm.csv",
        "metrics_path": Path("models") / "lightgbm" / "latest" / "metrics.json",
    },
]


def as_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        value = float(value)
        if not np.isfinite(value):
            return None
        return value
    except Exception:
        return None


def read_metrics(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def calc_ic(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 3:
        return None
    if pair["x"].std(ddof=0) < 1e-12 or pair["y"].std(ddof=0) < 1e-12:
        return None
    return as_float(np.corrcoef(pair["x"].values, pair["y"].values)[0, 1])


def calc_rankic(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.DataFrame({"x": x, "y": y}).replace([np.inf, -np.inf], np.nan).dropna()
    if len(pair) < 3:
        return None
    if pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    try:
        return as_float(spearmanr(pair["x"], pair["y"]).correlation)
    except Exception:
        return None


def mean_and_ir(values: list[float | None]) -> tuple[float | None, float | None]:
    x = pd.Series([v for v in values if v is not None], dtype=float).dropna()
    if x.empty:
        return None, None
    mean = x.mean()
    std = x.std()
    ir = mean / std if std and std > 1e-12 else None
    return as_float(mean), as_float(ir)


def infer_feature_set(metrics: dict, df: pd.DataFrame) -> str:
    feature_type = str(metrics.get("feature_type") or "")
    if "News" in feature_type or any(c.startswith("recent_news_count_") for c in df.columns):
        return "alpha158_news"
    return "alpha158"


def evaluate_prediction_file(model_backend: str, pred_path: Path, metrics_path: Path) -> dict | None:
    if not pred_path.exists():
        return None

    df = pd.read_csv(pred_path, encoding="utf-8-sig")
    if df.empty:
        return None

    metrics = read_metrics(metrics_path)
    df["date"] = pd.to_datetime(df["date"])
    pred_col = MODEL_PRED_COL if MODEL_PRED_COL in df.columns else "raw_score"

    daily_ic = []
    daily_rankic = []
    top10 = []
    top30 = []

    for _, g in df.groupby("date"):
        g = g.dropna(subset=[pred_col, "future_5d_ret"]).copy()
        if len(g) < 3:
            continue
        daily_ic.append(calc_ic(g[pred_col], g["future_5d_ret"]))
        daily_rankic.append(calc_rankic(g[pred_col], g["future_5d_ret"]))

        sorted_g = g.sort_values(pred_col, ascending=False)
        top10.append(as_float(sorted_g.head(10)["future_5d_ret"].mean()))
        top30.append(as_float(sorted_g.head(30)["future_5d_ret"].mean()))

    ic_mean, icir = mean_and_ir(daily_ic)
    rankic_mean, rankicir = mean_and_ir(daily_rankic)

    auc = None
    if "up_prob" in df.columns and "future_5d_up" in df.columns:
        try:
            auc = as_float(roc_auc_score(df["future_5d_up"], df["up_prob"]))
        except Exception:
            auc = None

    return {
        "model_backend": model_backend,
        "feature_set": infer_feature_set(metrics, df),
        "IC": ic_mean,
        "RankIC": rankic_mean,
        "ICIR": icir,
        "RankICIR": rankicir,
        "Top10Ret": as_float(pd.Series([x for x in top10 if x is not None]).mean()),
        "Top30Ret": as_float(pd.Series([x for x in top30 if x is not None]).mean()),
        "AUC": auc,
        "test_start": df["date"].min().strftime("%Y-%m-%d"),
        "test_end": df["date"].max().strftime("%Y-%m-%d"),
        "test_days": int(df["date"].nunique()),
        "test_rows": int(len(df)),
        "prediction_file": str(pred_path),
    }


def main() -> None:
    rows = []
    for item in MODEL_PREDICTION_FILES:
        row = evaluate_prediction_file(
            model_backend=item["model_backend"],
            pred_path=item["path"],
            metrics_path=item["metrics_path"],
        )
        if row is not None:
            rows.append(row)

    if not rows:
        raise RuntimeError("没有找到可用于对比的测试预测文件。")

    out = pd.DataFrame(rows)
    out = out.sort_values("RankIC", ascending=False, na_position="last").reset_index(drop=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(REPORT_PATH, index=False, encoding="utf-8-sig")

    print("=" * 80)
    print("[Model Compare Finished]")
    print(f"[Report] {REPORT_PATH}")
    print(out.to_string(index=False))
    print("=" * 80)


if __name__ == "__main__":
    main()
