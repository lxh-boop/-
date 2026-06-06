import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from alpha158 import (
    add_alpha158_features,
    get_alpha158_feature_cols,
    prepare_model_data,
)
from config import (
    EVAL_METRICS_PATH,
    LATEST_FEATURE_DATA_PATH,
    LATEST_RAW_DATA_PATH,
    MODEL_NAME,
    OUTPUT_DIR,
    RANKING_LATEST_PATH,
    START_DATE,
    STOCK_POOL,
    ensure_dirs,
)
from data_tushare import fetch_stock_pool_tushare
from model_store import load_torch_model_bundle, save_torch_model_bundle
from torch_trainer import predict_torch_mlp, train_torch_mlp

from universe import get_stock_pool

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


def evaluate_predictions(test_df: pd.DataFrame):
    daily_results = []

    for date, g in test_df.groupby("date"):
        g = g.dropna(subset=["pred_5d_ret", "future_5d_ret"]).copy()

        if len(g) < 3:
            continue

        ic = calc_ic(g["pred_5d_ret"].values, g["future_5d_ret"].values)
        rankic = calc_rankic(g["pred_5d_ret"].values, g["future_5d_ret"].values)

        top5_ret = (
            g.sort_values("pred_5d_ret", ascending=False)
            .head(5)["future_5d_ret"]
            .mean()
        )

        top10_ret = (
            g.sort_values("pred_5d_ret", ascending=False)
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
    eval_df.to_csv(EVAL_METRICS_PATH, index=False, encoding="utf-8-sig")

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


def risk_level(row):
    vol = row.get("vol_20", np.nan)
    dd = row.get("drawdown_20", np.nan)

    if pd.isna(vol) or pd.isna(dd):
        return "未知"

    if vol > 0.035 or dd < -0.15:
        return "高"

    if vol > 0.025 or dd < -0.10:
        return "中"

    return "低"


def confidence_level(row):
    prob = row["up_prob"]
    vol = row.get("vol_20", np.nan)

    distance = abs(prob - 0.5)

    if pd.isna(vol):
        return "中"

    if distance > 0.18 and vol < 0.03:
        return "高"

    if distance > 0.10 and vol < 0.04:
        return "中"

    return "低"


def make_latest_ranking(feature_data, model, scaler, feature_cols, model_name):
    latest_rows = []

    for code, g in feature_data.groupby("code"):
        g = g.sort_values("date").copy()
        latest = g.dropna(subset=feature_cols).tail(1)

        if not latest.empty:
            latest_rows.append(latest)

    if not latest_rows:
        raise RuntimeError("没有可用于预测的最新样本。")

    latest_df = pd.concat(latest_rows, ignore_index=True)

    pred_ret, up_prob = predict_torch_mlp(
        model=model,
        scaler=scaler,
        df=latest_df,
        feature_cols=feature_cols,
    )

    latest_df["pred_5d_ret"] = pred_ret
    latest_df["up_prob"] = up_prob

    latest_df["score"] = (
        latest_df["pred_5d_ret"].rank(pct=True) * 0.50
        + latest_df["up_prob"].rank(pct=True) * 0.40
        + latest_df["drawdown_20"].rank(pct=True) * 0.10
    )

    latest_df["risk_level"] = latest_df.apply(risk_level, axis=1)
    latest_df["confidence"] = latest_df.apply(confidence_level, axis=1)
    latest_df["model_name"] = model_name

    result = latest_df[
        [
            "date",
            "code",
            "name",
            "close",
            "pred_5d_ret",
            "up_prob",
            "score",
            "confidence",
            "risk_level",
            "model_name",
            "ret_5",
            "ret_20",
            "vol_20",
            "drawdown_20",
        ]
    ].copy()

    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", np.arange(1, len(result) + 1))

    result["code"] = result["code"].astype(str).str.zfill(6)

    result.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    dated_path = os.path.join(
        OUTPUT_DIR,
        f"ranking_{datetime.today().strftime('%Y%m%d')}_{model_name}.csv",
    )

    result.to_csv(dated_path, index=False, encoding="utf-8-sig")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")

    return result


def rolling_update(token: str, base_version: str = "latest"):
    """
    APP 每日自动调用的滚动更新。

    注意：
    - 会读取已有模型，确认本地模型存在；
    - 会抓取最新 Tushare 行情；
    - 会使用有 future_5d_ret 标签的数据重新训练；
    - 最新几天没有标签的数据不会参与训练；
    - 最后用新模型预测最新一日排名。
    """

    ensure_dirs()

    print("=" * 80)
    print("[Rolling Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    # 读取已有模型，确保 APP 看到的是已经训练好的本地模型
    base_bundle = load_torch_model_bundle(
        model_name=MODEL_NAME,
        version=base_version,
    )

    print(
        f"[Base Model] {base_bundle['model_name']} version={base_bundle['version']}"
    )

    stock_pool = get_stock_pool(token=token, enrich_name=True)
    print(f"[Universe] rolling update stock count = {len(stock_pool)}")

    raw_data = fetch_stock_pool_tushare(
        token=token,
        stock_pool=stock_pool,
        start_date=START_DATE,
        cache_path=LATEST_RAW_DATA_PATH,
    )

    feature_data = add_alpha158_features(
        raw_data,
        save_path=LATEST_FEATURE_DATA_PATH,
    )

    feature_cols = get_alpha158_feature_cols(feature_data)

    print(f"[Feature] count = {len(feature_cols)}")

    model_df = prepare_model_data(feature_data, feature_cols)

    if model_df.empty:
        raise RuntimeError("滚动训练数据为空，请检查 Tushare 数据和 Alpha158 因子。")

    dates = sorted(model_df["date"].unique())

    if len(dates) < 200:
        raise RuntimeError("可用交易日太少，无法滚动训练。")

    split_idx = int(len(dates) * 0.8)
    split_date = dates[split_idx]

    train_df = model_df[model_df["date"] < split_date].copy()
    test_df = model_df[model_df["date"] >= split_date].copy()

    model, scaler, test_pred_df, base_metrics = train_torch_mlp(
        train_df=train_df,
        test_df=test_df,
        feature_cols=feature_cols,
    )

    eval_metrics = evaluate_predictions(test_pred_df)

    metrics = {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_data_date": str(model_df["date"].max().date()),
        "split_date": str(pd.to_datetime(split_date).date()),
        "model_name": MODEL_NAME,
        "train_source": "tushare_rolling",
        "base_version": base_bundle["version"],
        "train_samples": int(len(train_df)),
        "test_samples": int(len(test_df)),
        "feature_type": "Alpha158",
        "feature_count": int(len(feature_cols)),
        "rmse": base_metrics.get("rmse"),
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

    save_torch_model_bundle(
        model_name=MODEL_NAME,
        model=model,
        scaler=scaler,
        feature_cols=feature_cols,
        metrics=metrics,
    )

    ranking = make_latest_ranking(
        feature_data=feature_data,
        model=model,
        scaler=scaler,
        feature_cols=feature_cols,
        model_name=MODEL_NAME,
    )

    print("[Top 5]")
    print(
        ranking.head(5)[
            [
                "rank",
                "code",
                "name",
                "pred_5d_ret",
                "up_prob",
                "score",
                "confidence",
                "risk_level",
            ]
        ]
    )

    print("=" * 80)
    print("[Rolling Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    return ranking, metrics


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--token",
        type=str,
        required=True,
        help="Tushare Token。滚动更新需要用它抓取最新行情。",
    )

    parser.add_argument(
        "--base-version",
        type=str,
        default="latest",
        help="基于哪个已有模型版本进行滚动更新，默认 latest。",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    rolling_update(
        token=args.token,
        base_version=args.base_version,
    )