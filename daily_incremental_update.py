import argparse
import json
import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import torch

from alpha158 import add_alpha158_features, get_alpha158_feature_cols, prepare_model_data
from calibration import ProbabilityCalibrator
from confidence_scoring import add_confidence_scores
from config import (
    DEFAULT_DFT_UNET_CHECKPOINT_PATH,
    DFT_UNET_FINETUNE_LOG_PATH,
    DFT_UNET_LATEST_METRICS_PATH,
    DFT_UNET_LATEST_MODEL_PATH,
    ENABLE_NEWS_FEATURES,
    LATEST_FEATURE_DATA_PATH,
    LATEST_RAW_DATA_PATH,
    METRICS_PATH,
    MODEL_PRED_COL,
    MODEL_REG_LABEL_COL,
    MODEL_NAME,
    OUTPUT_DIR,
    RANKING_LATEST_PATH,
    RAW_DATA_PATH,
    TRAIN_RAW_DATA_PATH,
    ensure_dirs,
)
from data_tushare import fetch_stock_pool_recent_daily_fast
from external_models.dft_unet_adapter import DFTUNetAdapter
from market_context import ensure_market_context_for_feature_data
from model_store import get_latest_dir, load_torch_model_bundle, save_torch_model_bundle
from model_zoo_backend import (
    is_zoo_backend,
    make_zoo_latest_ranking,
    validate_zoo_backend_environment,
    zoo_model_name_from_backend,
)
from news_features import NEWS_EVENT_FEATURE_COLUMNS, add_news_event_features
from ranking_schema import normalize_ranking_columns, validate_ranking_schema
from risk_scoring import add_risk_scores
from torch_trainer import predict_torch_mlp
from universe import get_stock_pool


TORCH_MLP_BACKEND = "torch_mlp_alpha158"
DFT_UNET_BACKEND = "dft_unet_external"


# ============================================================
# 1. 参数
# ============================================================

# Tushare 每天更新时，不需要从 2020 年重新拉。
# 为了防止节假日、停牌、网络漏数据，默认拉最近 10 天。
FETCH_RECENT_TRADE_DAYS = 10

# 增量微调参数。不要像初始训练那样训很多轮。
INCREMENTAL_EPOCHS = 5
INCREMENTAL_LR = 3e-4
BATCH_SIZE = 256


# ============================================================
# 2. 工具函数
# ============================================================

def normalize_raw_data(df: pd.DataFrame, stock_pool: dict) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"])

    stock_codes = set(stock_pool)
    df = df[df["code"].isin(stock_codes)].copy()

    mapped_names = df["code"].map(stock_pool)

    if "name" not in df.columns:
        df["name"] = mapped_names
    else:
        df["name"] = mapped_names.fillna(df["name"])

    if "pct_chg" not in df.columns:
        df["pct_chg"] = np.nan

    if "vwap" not in df.columns:
        df["vwap"] = df["close"]

    if "turnover" not in df.columns:
        df["turnover"] = 0.0

    needed_cols = [
        "date", "code", "name", "open", "close", "high", "low",
        "volume", "amount", "pct_chg", "vwap", "turnover",
    ]

    df = df[[c for c in needed_cols if c in df.columns]].copy()
    df = df.dropna(subset=["open", "close", "high", "low"])
    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    return df


def load_cached_raw_data(stock_pool: dict) -> pd.DataFrame:
    candidates = [
        LATEST_RAW_DATA_PATH,
        TRAIN_RAW_DATA_PATH,
        RAW_DATA_PATH,
    ]

    for path in candidates:
        if not os.path.exists(path):
            continue

        df = pd.read_csv(path, dtype={"code": str})
        df = normalize_raw_data(df, stock_pool)

        if df.empty:
            print(f"[Data] cache empty after CSI300 filter: {path}")
            continue

        print(f"[Data] use local cache: {path}")
        return df

    return pd.DataFrame()


def merge_raw_data(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    stock_pool: dict,
) -> pd.DataFrame:
    if old_df is None or old_df.empty:
        data = new_df.copy()
    elif new_df is None or new_df.empty:
        data = old_df.copy()
    else:
        data = pd.concat([old_df, new_df], ignore_index=True)

    data["code"] = data["code"].astype(str).str.zfill(6)
    data["date"] = pd.to_datetime(data["date"])

    data = data.drop_duplicates(subset=["code", "date"], keep="last")
    data = normalize_raw_data(data, stock_pool)
    data = data.sort_values(["code", "date"]).reset_index(drop=True)

    return data


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


def fit_probability_calibrator(
    feature_data: pd.DataFrame,
    model,
    scaler,
    feature_cols,
    model_name: str,
) -> ProbabilityCalibrator:
    calibrator = ProbabilityCalibrator(method="auto")

    try:
        model_df = prepare_model_data(feature_data, feature_cols)

        if model_df.empty:
            calibrator.fit([], [])
            return calibrator

        if len(model_df) > 10000:
            model_df = model_df.sort_values("date").tail(10000).copy()

        _, raw_up_prob = predict_torch_mlp(
            model=model,
            scaler=scaler,
            df=model_df,
            feature_cols=feature_cols,
        )
        calibrator.fit(model_df["future_5d_up"].values, raw_up_prob)
    except Exception as exc:
        calibrator.report = {
            "calibrated": False,
            "method": "identity",
            "reason": f"calibration failed: {type(exc).__name__}: {exc}",
        }

    try:
        calibrator_path = os.path.join(get_latest_dir(model_name), "calibrator.pkl")
        calibrator.save(calibrator_path)
        print(f"[Calibration] saved -> {calibrator_path}")
    except Exception as exc:
        print(f"[Calibration] save skipped: {exc}")

    print(f"[Calibration] report = {calibrator.report}")
    return calibrator


def persist_latest_metrics(model_name: str, metrics: dict) -> None:
    try:
        latest_metrics_path = os.path.join(get_latest_dir(model_name), "metrics.json")
        with open(latest_metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        joblib.dump(metrics, METRICS_PATH)
        print(f"[Metrics] latest metrics updated -> {latest_metrics_path}")
    except Exception as exc:
        print(f"[Metrics] latest metrics update skipped: {exc}")


# ============================================================
# 3. 增量微调
# ============================================================

def fine_tune_model_on_new_samples(
    model,
    scaler,
    feature_cols,
    feature_data: pd.DataFrame,
    last_train_date: str | None,
    new_data_start_date=None,
):
    """
    只用新增的有标签样本微调模型。

    注意：
    - 今天的数据没有 future_5d_ret，不能训练；
    - prepare_model_data 会自动丢掉没有 future_5d_ret 的最近样本；
    - 如果没有新可监督样本，就不训练模型，只预测最新排名。
    """

    model_df = prepare_model_data(feature_data, feature_cols)

    if model_df.empty:
        print("[Incremental Train] no labeled data, skip fine-tune")
        return model, None, 0

    model_df["date"] = pd.to_datetime(model_df["date"])

    if last_train_date:
        last_train_date = pd.to_datetime(last_train_date)
        new_train_df = model_df[model_df["date"] > last_train_date].copy()
    else:
        new_train_df = model_df.copy()

    if new_data_start_date is not None:
        new_data_start_date = pd.to_datetime(new_data_start_date)
        new_train_df = new_train_df[new_train_df["date"] >= new_data_start_date].copy()

    if new_train_df.empty:
        print("[Incremental Train] no new labeled samples, skip fine-tune")
        return model, None, 0

    print(f"[Incremental Train] new labeled samples = {len(new_train_df)}")
    print(
        f"[Incremental Train] date range = "
        f"{new_train_df['date'].min()} ~ {new_train_df['date'].max()}"
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    model.train()

    x = new_train_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0).values
    x = scaler.transform(x).astype(np.float32)

    y_reg = new_train_df[MODEL_REG_LABEL_COL].values.astype(np.float32)
    y_cls = new_train_df["future_5d_up"].values.astype(np.float32)

    x_tensor = torch.tensor(x, dtype=torch.float32)
    y_reg_tensor = torch.tensor(y_reg, dtype=torch.float32)
    y_cls_tensor = torch.tensor(y_cls, dtype=torch.float32)

    dataset = torch.utils.data.TensorDataset(x_tensor, y_reg_tensor, y_cls_tensor)
    loader = torch.utils.data.DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=INCREMENTAL_LR, weight_decay=1e-4)
    mse_loss = torch.nn.MSELoss()
    bce_loss = torch.nn.BCEWithLogitsLoss()

    for epoch in range(1, INCREMENTAL_EPOCHS + 1):
        total_loss = 0.0

        for batch_x, batch_y_reg, batch_y_cls in loader:
            batch_x = batch_x.to(device)
            batch_y_reg = batch_y_reg.to(device)
            batch_y_cls = batch_y_cls.to(device)

            pred_reg, pred_logit = model(batch_x)

            loss_reg = mse_loss(pred_reg, batch_y_reg)
            loss_cls = bce_loss(pred_logit, batch_y_cls)
            loss = loss_reg + loss_cls

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(batch_x)

        avg_loss = total_loss / len(dataset)
        print(f"[Incremental Train][Epoch {epoch}] loss={avg_loss:.6f}")

    model.eval()

    new_latest_train_date = str(new_train_df["date"].max().date())

    return model, new_latest_train_date, len(new_train_df)


# ============================================================
# 4. 生成最新排名
# ============================================================

def make_latest_ranking(feature_data, model, scaler, feature_cols, model_name):
    latest_rows = []

    for code, g in feature_data.groupby("code"):
        g = g.sort_values("date").copy()
        latest = g.dropna(subset=["close"]).tail(1)

        if not latest.empty:
            latest_rows.append(latest)

    if not latest_rows:
        raise RuntimeError("没有可用于预测的最新样本。")

    latest_df = pd.concat(latest_rows, ignore_index=True)

    pred_score, up_prob = predict_torch_mlp(
        model=model,
        scaler=scaler,
        df=latest_df,
        feature_cols=feature_cols,
    )

    latest_df[MODEL_PRED_COL] = pred_score
    latest_df["raw_score"] = pred_score
    latest_df["pred_5d_ret"] = pred_score
    latest_df["up_prob_raw"] = up_prob

    calibrator = fit_probability_calibrator(
        feature_data=feature_data,
        model=model,
        scaler=scaler,
        feature_cols=feature_cols,
        model_name=model_name,
    )
    calibration_report = dict(calibrator.report)
    latest_df["up_prob_calibrated"] = calibrator.predict_proba(up_prob)
    latest_df["up_prob"] = latest_df["up_prob_calibrated"]
    latest_df["calibrated"] = bool(calibration_report.get("calibrated", False))
    latest_df["calibration_method"] = calibration_report.get("method", "identity")
    latest_df["name"] = latest_df["name"].astype(str)
    numeric_name = latest_df["name"].str.fullmatch(r"\d+")
    latest_df.loc[numeric_name, "name"] = latest_df.loc[numeric_name, "name"].str.zfill(6)

    latest_df["score"] = latest_df[MODEL_PRED_COL].rank(pct=True)
    latest_df["model_name"] = model_name

    latest_df = add_risk_scores(latest_df)
    latest_df = add_confidence_scores(
        latest_df,
        calibration_report=calibration_report,
    )

    output_cols = [
        "date", "code", "name", "close", "pct_chg",
        "pred_5d_ret", "raw_score", MODEL_PRED_COL,
        "up_prob_raw", "up_prob", "up_prob_calibrated",
        "calibrated", "calibration_method", "score",
        "confidence_score", "confidence", "confidence_detail",
        "risk_score", "risk_level", "risk_detail", "model_name",
        "ret_5", "ret_20", "vol_20", "drawdown_20",
        *NEWS_EVENT_FEATURE_COLUMNS,
    ]

    result = latest_df[[c for c in output_cols if c in latest_df.columns]].copy()

    result = result.sort_values("score", ascending=False).reset_index(drop=True)
    result.insert(0, "rank", np.arange(1, len(result) + 1))

    result["code"] = result["code"].astype(str).str.zfill(6)
    result = normalize_ranking_columns(result)
    validate_ranking_schema(result)

    result.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    dated_path = os.path.join(
        OUTPUT_DIR,
        f"ranking_{datetime.today().strftime('%Y%m%d')}_{model_name}.csv",
    )
    result.to_csv(dated_path, index=False, encoding="utf-8-sig")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")

    return result, calibration_report


# ============================================================
# 5. 每日增量更新主流程
# ============================================================

def prepare_latest_feature_data(token: str):
    stock_pool = get_stock_pool(token=token, enrich_name=True)
    print(f"[Universe] update stock count = {len(stock_pool)}")

    old_raw = load_cached_raw_data(stock_pool)

    if old_raw.empty:
        print("[Data] no local latest cache, fallback to recent fetch only")
    else:
        print(f"[Data] cached raw shape = {old_raw.shape}")
        print(f"[Data] cached date range = {old_raw['date'].min()} ~ {old_raw['date'].max()}")

    print(f"[Data] fetch recent {FETCH_RECENT_TRADE_DAYS} trade days from Tushare")

    recent_raw = fetch_stock_pool_recent_daily_fast(
        token=token,
        stock_pool=stock_pool,
        recent_trade_days=FETCH_RECENT_TRADE_DAYS,
    )
    recent_raw = normalize_raw_data(recent_raw, stock_pool)

    if recent_raw.empty:
        raise RuntimeError("Tushare 最近行情为空，无法生成最新排名。")

    new_data_start_date = recent_raw["date"].min()

    raw_data = merge_raw_data(old_raw, recent_raw, stock_pool)
    raw_data.to_csv(LATEST_RAW_DATA_PATH, index=False, encoding="utf-8-sig")

    print(f"[Data] merged raw shape = {raw_data.shape}")
    print(f"[Data] merged stock count = {raw_data['code'].nunique()}")
    print(f"[Data] merged date range = {raw_data['date'].min()} ~ {raw_data['date'].max()}")

    feature_data = add_alpha158_features(
        raw_data,
        save_path=LATEST_FEATURE_DATA_PATH,
    )

    if ENABLE_NEWS_FEATURES:
        news_start_date = max(
            pd.to_datetime(raw_data["date"].min()),
            pd.to_datetime(raw_data["date"].max()) - pd.Timedelta(days=90),
        )
        feature_data = add_news_event_features(
            feature_data,
            stock_pool=stock_pool,
            token=token,
            refresh_cache=True,
            start_date=news_start_date,
            end_date=raw_data["date"].max(),
        )
        feature_data.to_csv(LATEST_FEATURE_DATA_PATH, index=False, encoding="utf-8-sig")
        print(f"[Save] latest feature data with news events -> {LATEST_FEATURE_DATA_PATH}, shape={feature_data.shape}")

    return feature_data, raw_data, new_data_start_date, stock_pool


def daily_incremental_update(token: str, base_version: str = "latest"):
    ensure_dirs()

    print("=" * 80)
    print("[Daily Incremental Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    bundle = load_torch_model_bundle(
        model_name=MODEL_NAME,
        version=base_version,
    )

    model = bundle["model"]
    scaler = bundle["scaler"]
    feature_cols = bundle["feature_cols"]
    old_metrics = bundle["metrics"]

    last_train_date = old_metrics.get("latest_data_date")
    print(f"[Model] loaded version = {bundle['version']}")
    print(f"[Model] last train date = {last_train_date}")

    feature_data, raw_data, new_data_start_date, _ = prepare_latest_feature_data(token)

    missing_features = [c for c in feature_cols if c not in feature_data.columns]

    if missing_features:
        raise RuntimeError(f"当前特征缺少训练时使用的字段：{missing_features[:20]}")

    model, new_latest_train_date, new_sample_count = fine_tune_model_on_new_samples(
        model=model,
        scaler=scaler,
        feature_cols=feature_cols,
        feature_data=feature_data,
        last_train_date=last_train_date,
        new_data_start_date=new_data_start_date,
    )

    new_metrics = dict(old_metrics)
    new_metrics["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_metrics["update_type"] = "daily_incremental"
    new_metrics["base_version"] = bundle["version"]
    new_metrics["model_backend"] = TORCH_MLP_BACKEND
    new_metrics["rolling_train_supported"] = True
    new_metrics["new_labeled_samples"] = int(new_sample_count)
    new_metrics["rolling_fine_tune_performed"] = bool(new_sample_count > 0)
    new_metrics["rolling_fine_tune_reason"] = (
        "new_labeled_samples_available"
        if new_sample_count > 0
        else "no_new_labeled_samples"
    )
    new_metrics["latest_raw_date"] = str(pd.to_datetime(raw_data["date"].max()).date())
    new_metrics["news_features_enabled"] = bool(ENABLE_NEWS_FEATURES)
    new_metrics["feature_type"] = "Alpha158+NewsEvents" if ENABLE_NEWS_FEATURES else new_metrics.get("feature_type", "Alpha158")

    if new_latest_train_date:
        new_metrics["latest_data_date"] = new_latest_train_date

    # 只要发生了微调，就保存新模型版本。
    # 如果没有新可监督样本，也可以不保存模型，只生成排名。
    if new_sample_count > 0:
        save_torch_model_bundle(
            model_name=MODEL_NAME,
            model=model,
            scaler=scaler,
            feature_cols=feature_cols,
            metrics=new_metrics,
        )
        print("[Model] incremental model saved")
    else:
        print("[Model] no new labeled sample, model not saved")

    ranking, calibration_report = make_latest_ranking(
        feature_data=feature_data,
        model=model,
        scaler=scaler,
        feature_cols=feature_cols,
        model_name=MODEL_NAME,
    )
    if not ranking.empty and "date" in ranking.columns:
        new_metrics["prediction_signal_date"] = str(pd.to_datetime(ranking["date"].iloc[0]).date())
    new_metrics["prediction_horizon"] = "next_trading_day_T_plus_1"
    new_metrics["calibration_report"] = calibration_report
    new_metrics["calibrated"] = bool(calibration_report.get("calibrated", False))
    persist_latest_metrics(MODEL_NAME, new_metrics)

    print("[Top 5]")
    print(
        ranking.head(5)[
            [
                "rank", "code", "name",
                MODEL_PRED_COL, "up_prob", "score",
                "confidence", "risk_level",
            ]
        ]
    )

    print("=" * 80)
    print("[Daily Incremental Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    return ranking, new_metrics


def external_dft_unet_daily_update(
    token: str,
    checkpoint_path: str = DEFAULT_DFT_UNET_CHECKPOINT_PATH,
):
    ensure_dirs()

    print("=" * 80)
    print("[External DFT_UNET Daily Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    source_checkpoint = DFT_UNET_LATEST_MODEL_PATH if os.path.exists(DFT_UNET_LATEST_MODEL_PATH) else checkpoint_path
    print("[Model] external checkpoint =", source_checkpoint)
    print("[Model] external DFT_UNET rolling fine-tune is enabled when new labeled samples exist.")

    feature_data, raw_data, new_data_start_date, _ = prepare_latest_feature_data(token)
    feature_data, market_context_report = ensure_market_context_for_feature_data(
        feature_data=feature_data,
        token=token,
    )

    old_metrics = {}
    if os.path.exists(DFT_UNET_LATEST_METRICS_PATH):
        try:
            with open(DFT_UNET_LATEST_METRICS_PATH, "r", encoding="utf-8") as f:
                old_metrics = json.load(f)
        except Exception:
            old_metrics = {}

    adapter = DFTUNetAdapter(checkpoint_path=source_checkpoint, device="cpu").load()
    fine_tune_report = adapter.fine_tune(
        feature_data=feature_data,
        last_train_date=old_metrics.get("latest_data_date"),
        new_data_start_date=new_data_start_date,
        epochs=3,
        lr=1e-4,
        batch_size=128,
        save_path=DFT_UNET_LATEST_MODEL_PATH,
    )
    ranking = adapter.predict(raw_data=raw_data, feature_data=feature_data)

    ranking.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    date_text = datetime.today().strftime("%Y%m%d")
    if "date" in ranking.columns and not ranking.empty:
        date_text = str(ranking["date"].iloc[0]).replace("-", "")[:8]

    dated_path = os.path.join(OUTPUT_DIR, f"ranking_{date_text}_dft_unet_external.csv")
    ranking.to_csv(dated_path, index=False, encoding="utf-8-sig")

    metrics = {
        "model_name": "dft_unet_external",
        "model_backend": DFT_UNET_BACKEND,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_type": "daily_dft_unet_rolling_update",
        "rolling_train_supported": True,
        "rolling_fine_tune_performed": bool(fine_tune_report.get("fine_tuned", False)),
        "rolling_fine_tune_reason": fine_tune_report.get("reason", "new_labeled_samples_available"),
        "new_labeled_samples": int(fine_tune_report.get("new_labeled_samples", 0) or 0),
        "latest_data_date": fine_tune_report.get("train_end_date") or old_metrics.get("latest_data_date"),
        "checkpoint_path": str(source_checkpoint),
        "latest_model_path": DFT_UNET_LATEST_MODEL_PATH,
        "fine_tune_report": fine_tune_report,
        "latest_raw_date": str(pd.to_datetime(raw_data["date"].max()).date()) if not raw_data.empty else "",
        "prediction_signal_date": str(pd.to_datetime(ranking["date"].iloc[0]).date()) if not ranking.empty and "date" in ranking.columns else "",
        "prediction_horizon": "next_trading_day_T_plus_1",
        "ranking_rows": int(len(ranking)),
        "market_context_report": market_context_report,
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }

    metrics_path = os.path.join(OUTPUT_DIR, "external_dft_unet_latest_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    os.makedirs(os.path.dirname(DFT_UNET_LATEST_METRICS_PATH), exist_ok=True)
    with open(DFT_UNET_LATEST_METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    try:
        log_row = {
            "update_time": metrics["update_time"],
            "fine_tuned": metrics["rolling_fine_tune_performed"],
            "new_labeled_samples": metrics["new_labeled_samples"],
            "latest_data_date": metrics.get("latest_data_date", ""),
            "loss": fine_tune_report.get("loss"),
            "checkpoint_path": metrics["checkpoint_path"],
            "latest_model_path": metrics["latest_model_path"],
        }
        log_df = pd.DataFrame([log_row])
        if os.path.exists(DFT_UNET_FINETUNE_LOG_PATH):
            old_log = pd.read_csv(DFT_UNET_FINETUNE_LOG_PATH, encoding="utf-8-sig")
            log_df = pd.concat([old_log, log_df], ignore_index=True)
        log_df.to_csv(DFT_UNET_FINETUNE_LOG_PATH, index=False, encoding="utf-8-sig")
    except Exception as exc:
        print(f"[DFT_UNET FineTune Log] skipped: {exc}")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")
    print(f"[Save] external metrics -> {metrics_path}")
    print("[Top 5]")
    print(ranking.head(5)[["rank", "code", "name", "raw_score", "up_prob", "score", "confidence", "risk_level"]])
    print("=" * 80)
    print("[External DFT_UNET Daily Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)

    return ranking, metrics


def model_zoo_daily_update(
    token: str,
    model_backend: str,
):
    ensure_dirs()

    zoo_model_name = zoo_model_name_from_backend(model_backend)
    print("=" * 80)
    print("[Model Zoo Daily Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    print("[Model Zoo] model =", zoo_model_name)
    print("[Model Zoo] rolling-window prediction is used; foundation model weights are not changed.")

    ok, message = validate_zoo_backend_environment(zoo_model_name)
    if not ok:
        raise RuntimeError(f"[Model Zoo Preflight Failed] {message}")
    print("[Model Zoo Preflight]", message)

    feature_data, raw_data, _, _ = prepare_latest_feature_data(token)
    ranking = make_zoo_latest_ranking(
        model_name=zoo_model_name,
        raw_data=raw_data,
        feature_data=feature_data,
        device="cpu",
    )
    ranking.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    date_text = datetime.today().strftime("%Y%m%d")
    if "date" in ranking.columns and not ranking.empty:
        date_text = str(ranking["date"].iloc[0]).replace("-", "")[:8]

    dated_path = os.path.join(OUTPUT_DIR, f"ranking_{date_text}_{zoo_model_name}.csv")
    ranking.to_csv(dated_path, index=False, encoding="utf-8-sig")

    metrics = {
        "model_name": zoo_model_name,
        "model_backend": model_backend,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_type": "daily_model_zoo_rolling_prediction",
        "rolling_train_supported": True,
        "rolling_training_mode": "rolling_window_prediction",
        "rolling_fine_tune_performed": False,
        "rolling_fine_tune_reason": "external_foundation_model_uses_rolling_window_prediction_without_parameter_update",
        "new_labeled_samples": 0,
        "latest_raw_date": str(pd.to_datetime(raw_data["date"].max()).date()) if not raw_data.empty else "",
        "prediction_signal_date": str(pd.to_datetime(ranking["date"].iloc[0]).date()) if not ranking.empty and "date" in ranking.columns else "",
        "prediction_horizon": "next_trading_day_T_plus_1",
        "ranking_rows": int(len(ranking)),
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }
    metrics_path = os.path.join(OUTPUT_DIR, "model_zoo_latest_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")
    print(f"[Save] model zoo metrics -> {metrics_path}")
    print("[Top 5]")
    print(ranking.head(5)[["rank", "code", "name", "raw_score", "up_prob", "score", "confidence", "risk_level"]])
    print("=" * 80)
    print("[Model Zoo Daily Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    return ranking, metrics


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--token",
        type=str,
        required=True,
        help="Tushare Token。",
    )

    parser.add_argument(
        "--base-version",
        type=str,
        default="latest",
        help="基于哪个已有模型版本进行每日增量更新，默认 latest。",
    )
    parser.add_argument(
        "--model-backend",
        type=str,
        default=TORCH_MLP_BACKEND,
        help="每日更新使用的模型库模型。",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default=DEFAULT_DFT_UNET_CHECKPOINT_PATH,
        help="External DFT_UNET checkpoint 路径。",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.model_backend == DFT_UNET_BACKEND:
        external_dft_unet_daily_update(
            token=args.token,
            checkpoint_path=args.checkpoint_path,
        )
    elif is_zoo_backend(args.model_backend):
        model_zoo_daily_update(
            token=args.token,
            model_backend=args.model_backend,
        )
    else:
        daily_incremental_update(
            token=args.token,
            base_version=args.base_version,
        )
