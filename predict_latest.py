import argparse
import os
from datetime import datetime

import numpy as np
import pandas as pd

from alpha158 import add_alpha158_features
from config import (
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
from model_store import load_torch_model_bundle
from torch_trainer import predict_torch_mlp


def risk_level(row):
    vol = row.get("vol_20", np.nan)
    dd = row.get("drawdown_20", np.nan)

    if pd.isna(vol) or pd.isna(dd):
        return "未知"

    if vol > 0.035 or dd < -0.15:
        return "高"
    elif vol > 0.025 or dd < -0.10:
        return "中"
    else:
        return "低"


def confidence_level(row):
    prob = row["up_prob"]
    vol = row.get("vol_20", np.nan)

    distance = abs(prob - 0.5)

    if pd.isna(vol):
        return "中"

    if distance > 0.18 and vol < 0.03:
        return "高"
    elif distance > 0.10 and vol < 0.04:
        return "中"
    else:
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
            "date", "code", "name", "close",
            "pred_5d_ret", "up_prob", "score",
            "confidence", "risk_level", "model_name",
            "ret_5", "ret_20", "vol_20", "drawdown_20",
        ]
    ].copy()

    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", np.arange(1, len(result) + 1))

    result["code"] = result["code"].astype(str).str.zfill(6)

    result.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    dated_path = os.path.join(
        OUTPUT_DIR,
        f"ranking_{datetime.today().strftime('%Y%m%d')}_{model_name}.csv"
    )
    result.to_csv(dated_path, index=False, encoding="utf-8-sig")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")

    return result


def predict_latest(token: str, version: str = "latest"):
    ensure_dirs()

    print("=" * 80)
    print("[Predict Latest Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    bundle = load_torch_model_bundle(
        model_name=MODEL_NAME,
        version=version,
    )

    model = bundle["model"]
    scaler = bundle["scaler"]
    feature_cols = bundle["feature_cols"]
    metrics = bundle["metrics"]

    raw_data = fetch_stock_pool_tushare(
        token=token,
        stock_pool=STOCK_POOL,
        start_date=START_DATE,
        cache_path=LATEST_RAW_DATA_PATH,
    )

    feature_data = add_alpha158_features(
        raw_data,
        save_path=LATEST_FEATURE_DATA_PATH,
    )

    missing_features = [
        c for c in feature_cols
        if c not in feature_data.columns
    ]

    if missing_features:
        raise RuntimeError(f"当前特征缺少训练时使用的字段：{missing_features[:20]}")

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
                "rank", "code", "name",
                "pred_5d_ret", "up_prob", "score",
                "confidence", "risk_level",
            ]
        ]
    )

    print("=" * 80)
    print("[Predict Latest Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    return ranking, metrics


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--token",
        type=str,
        default=None,
        help="Tushare Token。如果不填，则读取环境变量 TUSHARE_TOKEN。"
    )

    parser.add_argument(
        "--version",
        type=str,
        default="latest",
        help="读取哪个模型版本，默认 latest。"
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    predict_latest(token=args.token, version=args.version)