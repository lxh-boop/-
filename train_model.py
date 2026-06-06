import argparse
import json
import os
import shutil
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score
from scipy.stats import spearmanr

from alpha158 import (
    add_alpha158_features,
    get_alpha158_feature_cols,
    prepare_model_data,
)
from config import (
    ENABLE_NEWS_FEATURES,
    EVAL_METRICS_PATH,
    LOCAL_TRAIN_SOURCE,
    MODEL_DIR,
    MODEL_PRED_COL,
    MODEL_REG_LABEL_COL,
    MODEL_NAME,
    TEST_PREDICTIONS_PATH,
    TRAIN_FEATURE_DATA_PATH,
    ensure_dirs,
)
from data_local import load_local_train_data
from model_backends.lightgbm_backend import LightGBMBackend
from model_store import save_torch_model_bundle
from news_features import add_news_event_features, get_news_event_feature_cols
from torch_trainer import split_train_valid_by_date, train_torch_mlp

from universe import get_stock_pool

MIN_TRAIN_DAYS = 80
TORCH_MLP_BACKEND = "torch_mlp"
LIGHTGBM_BACKEND = "lightgbm"


def calc_ic(x, y):
    if len(x) < 3:
        return np.nan

    if np.std(x) < 1e-12 or np.std(y) < 1e-12:
        return np.nan

    return np.corrcoef(x, y)[0, 1]


def calc_rankic(x, y):
    if len(x) < 3:
        return np.nan

    try:
        return spearmanr(x, y).correlation
    except Exception:
        return np.nan


def evaluate_predictions(test_df: pd.DataFrame, output_path: str = EVAL_METRICS_PATH):
    daily_results = []

    for date, g in test_df.groupby("date"):
        g = g.dropna(subset=[MODEL_PRED_COL, MODEL_REG_LABEL_COL, "future_5d_ret"]).copy()

        if len(g) < 3:
            continue

        ic = calc_ic(g[MODEL_PRED_COL].values, g[MODEL_REG_LABEL_COL].values)
        rankic = calc_rankic(g[MODEL_PRED_COL].values, g[MODEL_REG_LABEL_COL].values)

        top5_ret = (
            g.sort_values(MODEL_PRED_COL, ascending=False)
            .head(5)["future_5d_ret"]
            .mean()
        )

        top10_ret = (
            g.sort_values(MODEL_PRED_COL, ascending=False)
            .head(10)["future_5d_ret"]
            .mean()
        )

        daily_results.append(
            {
                "date": date,
                "ic": ic,
                "rankic": rankic,
                "top5_ret": top5_ret,
                "top10_ret": top10_ret,
            }
        )

    eval_df = pd.DataFrame(daily_results)
    eval_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    if eval_df.empty:
        return {
            "ic_mean": None,
            "icir": None,
            "rankic_mean": None,
            "rankicir": None,
            "top5_mean_ret": None,
            "top10_mean_ret": None,
        }

    ic_mean = eval_df["ic"].mean()
    ic_std = eval_df["ic"].std()
    rankic_mean = eval_df["rankic"].mean()
    rankic_std = eval_df["rankic"].std()

    return {
        "ic_mean": float(ic_mean) if not pd.isna(ic_mean) else None,
        "icir": float(ic_mean / ic_std)
        if ic_std and not pd.isna(ic_std) and ic_std > 1e-12
        else None,
        "rankic_mean": float(rankic_mean) if not pd.isna(rankic_mean) else None,
        "rankicir": float(rankic_mean / rankic_std)
        if rankic_std and not pd.isna(rankic_std) and rankic_std > 1e-12
        else None,
        "top5_mean_ret": float(eval_df["top5_ret"].mean()),
        "top10_mean_ret": float(eval_df["top10_ret"].mean()),
    }


def save_test_predictions(
    test_pred_df: pd.DataFrame,
    output_path: str = TEST_PREDICTIONS_PATH,
) -> pd.DataFrame:
    out = test_pred_df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["code"] = out["code"].astype(str).str.zfill(6)
    if "raw_score" not in out.columns and MODEL_PRED_COL in out.columns:
        out["raw_score"] = out[MODEL_PRED_COL]
    if "pred_5d_ret" not in out.columns and MODEL_PRED_COL in out.columns:
        out["pred_5d_ret"] = out[MODEL_PRED_COL]

    out["score"] = (
        out.groupby("date")[MODEL_PRED_COL].rank(pct=True)
    )

    output_cols = [
        "date",
        "code",
        "name",
        "close",
        "pred_5d_ret",
        "raw_score",
        MODEL_PRED_COL,
        "up_prob",
        "score",
        MODEL_REG_LABEL_COL,
        "future_5d_ret",
        "future_5d_up",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
    ]

    out = out[[c for c in output_cols if c in out.columns]].copy()
    out = out.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"[Save] test predictions -> {output_path}, shape={out.shape}")

    return out


def backend_output_path(base_path: str, model_backend: str) -> str:
    if model_backend == TORCH_MLP_BACKEND:
        return base_path
    root, ext = os.path.splitext(base_path)
    return f"{root}_{model_backend}{ext}"


def save_generic_backend_bundle(model_name: str, backend, metrics: dict):
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_root = os.path.join(MODEL_DIR, model_name)
    version_dir = os.path.join(model_root, version)
    latest_dir = os.path.join(model_root, "latest")

    backend.metrics = metrics
    backend.save(version_dir)

    if os.path.exists(latest_dir):
        shutil.rmtree(latest_dir)
    shutil.copytree(version_dir, latest_dir)

    latest_info = {
        "model_name": model_name,
        "latest_version": version,
        "latest_dir": latest_dir,
        "bundle_path": os.path.join(latest_dir, f"{model_name}_backend.pkl"),
    }

    latest_info_path = os.path.join(model_root, "latest_info.json")
    with open(latest_info_path, "w", encoding="utf-8") as f:
        json.dump(latest_info, f, ensure_ascii=False, indent=2)

    print(f"[Save] {model_name} model bundle -> {version_dir}")
    print(f"[Save] latest {model_name} model -> {latest_dir}")

    return latest_info


def evaluate_lightgbm_test(test_pred_df: pd.DataFrame) -> dict:
    pred_cls = (test_pred_df["up_prob"] >= 0.5).astype(int)
    try:
        auc = roc_auc_score(test_pred_df["future_5d_up"], test_pred_df["up_prob"])
    except Exception:
        auc = np.nan

    return {
        "rmse": float(mean_squared_error(test_pred_df["future_5d_ret"], test_pred_df["pred_5d_ret"]) ** 0.5),
        "score_rmse": float(mean_squared_error(test_pred_df[MODEL_REG_LABEL_COL], test_pred_df[MODEL_PRED_COL]) ** 0.5),
        "accuracy": float(accuracy_score(test_pred_df["future_5d_up"], pred_cls)),
        "auc": float(auc) if not np.isnan(auc) else None,
    }


def train_model(
    source: str = LOCAL_TRAIN_SOURCE,
    model_backend: str = TORCH_MLP_BACKEND,
):
    """
    初始训练模型。
    只使用本地数据，不需要 Tushare Token，不依赖 APP。
    """

    ensure_dirs()

    print("=" * 80)
    print("[Initial Train Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print(f"[Train Source] {source}")
    print(f"[Model Backend] {model_backend}")
    print("=" * 80)

    stock_pool = get_stock_pool(token=None, enrich_name=False)
    print(f"[Universe] train stock count = {len(stock_pool)}")

    raw_data = load_local_train_data(source=source)

    feature_data = add_alpha158_features(
        raw_data,
        save_path=TRAIN_FEATURE_DATA_PATH,
    )

    if ENABLE_NEWS_FEATURES:
        feature_data = add_news_event_features(
            feature_data,
            stock_pool=stock_pool,
            refresh_cache=False,
        )
        feature_data.to_csv(TRAIN_FEATURE_DATA_PATH, index=False, encoding="utf-8-sig")
        print(f"[Save] feature data with news events -> {TRAIN_FEATURE_DATA_PATH}, shape={feature_data.shape}")

    feature_cols = get_alpha158_feature_cols(feature_data)

    print(f"[Feature] count = {len(feature_cols)}")

    expected_feature_count = 158 + (len(get_news_event_feature_cols()) if ENABLE_NEWS_FEATURES else 0)

    if len(feature_cols) != expected_feature_count:
        print(f"[Warning] 当前特征数量不是 {expected_feature_count}，而是 {len(feature_cols)}")

    model_df = prepare_model_data(feature_data, feature_cols)

    if model_df.empty:
        raise RuntimeError("训练数据为空，请检查本地数据和 Alpha158 因子。")

    dates = sorted(model_df["date"].unique())

    print(f"[Data] available labeled trading days = {len(dates)}")
    print(f"[Data] labeled sample shape = {model_df.shape}")
    print(
        f"[Data] labeled date range = "
        f"{model_df['date'].min()} ~ {model_df['date'].max()}"
    )

    if len(dates) < MIN_TRAIN_DAYS:
        raise RuntimeError(
            f"可用交易日太少，无法训练。当前 {len(dates)}，至少需要 {MIN_TRAIN_DAYS}。"
        )

    split_idx = int(len(dates) * 0.8)
    split_date = dates[split_idx]

    train_df = model_df[model_df["date"] < split_date].copy()
    test_df = model_df[model_df["date"] >= split_date].copy()

    model_backend = model_backend.strip().lower()
    model_name = MODEL_NAME if model_backend == TORCH_MLP_BACKEND else model_backend

    if model_backend == TORCH_MLP_BACKEND:
        model, scaler, test_pred_df, base_metrics = train_torch_mlp(
            train_df=train_df,
            test_df=test_df,
            feature_cols=feature_cols,
        )
        test_pred_df["raw_score"] = test_pred_df[MODEL_PRED_COL]
        test_pred_df["pred_5d_ret"] = test_pred_df[MODEL_PRED_COL]
        backend_obj = None
    elif model_backend == LIGHTGBM_BACKEND:
        inner_train_df, valid_df = split_train_valid_by_date(train_df, valid_ratio=0.2)
        backend_obj = LightGBMBackend().fit(
            train_df=inner_train_df,
            valid_df=valid_df,
            feature_cols=feature_cols,
        )
        pred_df = backend_obj.predict(test_df, feature_cols)
        test_pred_df = test_df.copy()
        for col in pred_df.columns:
            test_pred_df[col] = pred_df[col].values
        test_pred_df["pred_cls"] = (test_pred_df["up_prob"] >= 0.5).astype(int)
        base_metrics = evaluate_lightgbm_test(test_pred_df)
        base_metrics.update(
            {
                "valid_return_rmse": backend_obj.metrics.get("valid_return_rmse"),
                "valid_rank_rmse": backend_obj.metrics.get("valid_rank_rmse"),
                "valid_accuracy": backend_obj.metrics.get("valid_accuracy"),
                "valid_auc": backend_obj.metrics.get("valid_auc"),
            }
        )
    else:
        raise ValueError(f"未知模型后端：{model_backend}")

    eval_path = backend_output_path(EVAL_METRICS_PATH, model_backend)
    test_pred_path = backend_output_path(TEST_PREDICTIONS_PATH, model_backend)
    eval_metrics = evaluate_predictions(test_pred_df, output_path=eval_path)
    save_test_predictions(test_pred_df, output_path=test_pred_path)

    metrics = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_data_date": str(model_df["date"].max().date()),
        "split_date": str(pd.to_datetime(split_date).date()),
        "model_name": model_name,
        "model_backend": model_backend,
        "train_source": source,
        "train_samples": int(len(train_df)),
        "test_samples": int(len(test_df)),
        "feature_type": "Alpha158+NewsEvents" if ENABLE_NEWS_FEATURES else "Alpha158",
        "feature_count": int(len(feature_cols)),
        "news_features_enabled": bool(ENABLE_NEWS_FEATURES),
        "news_feature_count": len(get_news_event_feature_cols()) if ENABLE_NEWS_FEATURES else 0,
        "regression_target": MODEL_REG_LABEL_COL,
        "prediction_column": MODEL_PRED_COL,
        "target_normalization": "daily_cross_sectional_zscore",
        "rmse": base_metrics.get("rmse"),
        "score_rmse": base_metrics.get("score_rmse"),
        "accuracy": base_metrics.get("accuracy"),
        "auc": base_metrics.get("auc"),
        "best_valid_loss": base_metrics.get("best_valid_loss"),
        "device": base_metrics.get("device"),
        "ic_mean": eval_metrics.get("ic_mean"),
        "icir": eval_metrics.get("icir"),
        "rankic_mean": eval_metrics.get("rankic_mean"),
        "rankicir": eval_metrics.get("rankicir"),
        "top5_mean_ret": eval_metrics.get("top5_mean_ret"),
        "top10_mean_ret": eval_metrics.get("top10_mean_ret"),
        "features": feature_cols,
    }

    if model_backend == TORCH_MLP_BACKEND:
        save_torch_model_bundle(
            model_name=MODEL_NAME,
            model=model,
            scaler=scaler,
            feature_cols=feature_cols,
            metrics=metrics,
        )
    else:
        save_generic_backend_bundle(
            model_name=model_name,
            backend=backend_obj,
            metrics=metrics,
        )

    print("[Metrics]")
    print(metrics)

    print("=" * 80)
    print("[Initial Train Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        type=str,
        default=LOCAL_TRAIN_SOURCE,
        choices=["qlib", "csv"],
        help="本地训练数据源：qlib 或 csv。不需要 Tushare Token。",
    )
    parser.add_argument(
        "--model-backend",
        type=str,
        default=TORCH_MLP_BACKEND,
        choices=[TORCH_MLP_BACKEND, LIGHTGBM_BACKEND],
        help="模型后端：torch_mlp 或 lightgbm。",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train_model(source=args.source, model_backend=args.model_backend)
