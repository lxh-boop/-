import argparse
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from alpha158 import add_alpha158_features
from config import (
    ENABLE_NEWS_FEATURES,
    AGENT_QUANT_DB_PATH,
    DEFAULT_DFT_UNET_CHECKPOINT_PATH,
    DFT_UNET_FINETUNE_LOG_PATH,
    DFT_UNET_LATEST_METRICS_PATH,
    DFT_UNET_LATEST_MODEL_PATH,
    LATEST_FEATURE_DATA_PATH,
    LATEST_RAW_DATA_PATH,
    OUTPUT_DIR,
    RANKING_LATEST_PATH,
    RAW_DATA_PATH,
    TRAIN_RAW_DATA_PATH,
    ensure_dirs,
)
from data_tushare import fetch_stock_pool_recent_daily_fast
from market_context import ensure_market_context_for_feature_data
from model_zoo_backend import (
    is_zoo_backend,
    make_zoo_latest_ranking,
    validate_zoo_backend_environment,
    zoo_model_name_from_backend,
)
from news_features import add_news_event_features
from news_db_sync import sync_event_cache_to_agent_db
from pipelines.daily_update_pipeline import run_daily_update_pipeline
from pipelines.schemas import PipelineContext
from universe import get_stock_pool

# ============================================================
# 1. 参数
# ============================================================

# Tushare 每天更新时，不需要从 2020 年重新拉。
# 为了防止节假日、停牌、网络漏数据，默认拉最近 10 天。
FETCH_RECENT_TRADE_DAYS = 10

DFT_UNET_BACKEND = "dft_unet_external"
DEFAULT_EXTERNAL_MODEL_BACKEND = "zoo:chronos_bolt_small"


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


# ============================================================
# 3. 每日增量更新主流程
# ============================================================

def refresh_news_cache_and_sync_db(
    feature_data: pd.DataFrame,
    raw_data: pd.DataFrame,
    stock_pool: dict,
    token: str | None,
    refresh_cache: bool = True,
) -> dict:
    if not ENABLE_NEWS_FEATURES or feature_data.empty or raw_data.empty:
        return {"enabled": False, "reason": "news_features_disabled_or_empty_data"}

    news_start_date = max(
        pd.to_datetime(raw_data["date"].min()),
        pd.to_datetime(raw_data["date"].max()) - pd.Timedelta(days=90),
    )
    news_end_date = pd.to_datetime(raw_data["date"].max())

    if refresh_cache:
        _ = add_news_event_features(
            feature_data.copy(),
            stock_pool=stock_pool,
            token=token,
            refresh_cache=True,
            start_date=news_start_date,
            end_date=news_end_date,
        )
        print("[News] cache refreshed for AI adjustment; model feature table remains K-line only.")

    news_sync = sync_event_cache_to_agent_db(
        stock_pool=stock_pool,
        db_path=AGENT_QUANT_DB_PATH,
        output_dir=OUTPUT_DIR,
        start_date=news_start_date.strftime("%Y-%m-%d"),
        end_date=news_end_date.strftime("%Y-%m-%d"),
    )
    status = news_sync.to_dict()
    print(f"[News DB] sync status = {status}")
    return status


def prepare_latest_feature_data(
    token: str,
    include_news_features: bool = True,
    sync_news_db: bool = True,
    fetch_workers: int | None = None,
):
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
        max_workers=fetch_workers,
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

    if ENABLE_NEWS_FEATURES and include_news_features:
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

    if sync_news_db:
        refresh_news_cache_and_sync_db(
            feature_data=feature_data,
            raw_data=raw_data,
            stock_pool=stock_pool,
            token=token,
            refresh_cache=not (ENABLE_NEWS_FEATURES and include_news_features),
        )

    return feature_data, raw_data, new_data_start_date, stock_pool


def keep_existing_ranking_when_prediction_unavailable(
    model_backend: str,
    zoo_model_name: str,
    message: str,
    raw_data: pd.DataFrame,
    feature_data: pd.DataFrame,
):
    if not os.path.exists(RANKING_LATEST_PATH):
        raise RuntimeError(f"[Model Zoo Preflight Failed] {message}")

    ranking = pd.read_csv(RANKING_LATEST_PATH, dtype={"code": str})
    if "code" in ranking.columns:
        ranking["code"] = ranking["code"].astype(str).str.zfill(6)

    metrics = {
        "model_name": zoo_model_name,
        "model_backend": model_backend,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_type": "daily_data_update_prediction_skipped",
        "status": "prediction_skipped_dependency_unavailable",
        "dependency_message": message,
        "data_cache_updated": True,
        "ranking_preserved": True,
        "rolling_train_supported": False,
        "rolling_training_mode": "skipped",
        "model_feature_source": "kline_alpha158_only",
        "news_used_by_model": False,
        "news_synced_for_agent": False,
        "rolling_fine_tune_performed": False,
        "rolling_fine_tune_reason": "dependency_unavailable",
        "new_labeled_samples": 0,
        "latest_raw_date": str(pd.to_datetime(raw_data["date"].max()).date()) if not raw_data.empty else "",
        "latest_feature_date": str(pd.to_datetime(feature_data["date"].max()).date()) if not feature_data.empty and "date" in feature_data.columns else "",
        "ranking_rows": int(len(ranking)),
        "ranking_source": RANKING_LATEST_PATH,
        "disclaimer": "本项目仅用于机器学习、金融数据分析和项目展示，不构成投资建议，不用于实盘交易。",
    }
    metrics_path = os.path.join(OUTPUT_DIR, "model_zoo_latest_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print("[Model Zoo Preflight Skipped Prediction]", message)
    print(f"[Data] latest raw/feature cache updated; preserve existing ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] model zoo metrics -> {metrics_path}")
    return ranking, metrics


def run_post_prediction_ai_adjustment(
    user_id: str = "default",
    top_k: int = 50,
    output_dir: str = OUTPUT_DIR,
    db_path: str | None = None,
    paper_trading_enabled: bool = False,
    dry_run: bool = False,
):
    context = PipelineContext(
        user_id=user_id,
        trade_date="latest",
        top_k=int(top_k),
        output_dir=output_dir,
        db_path=db_path,
        dry_run=bool(dry_run),
        paper_trading_enabled=bool(paper_trading_enabled),
    )
    steps = ["prediction", "rag", "scoring"]
    if paper_trading_enabled:
        steps.append("paper")
    steps.append("report")
    return run_daily_update_pipeline(context, steps)


def model_zoo_daily_update(
    token: str,
    model_backend: str,
    fetch_workers: int | None = None,
):
    ensure_dirs()

    zoo_model_name = zoo_model_name_from_backend(model_backend)
    print("=" * 80)
    print("[Model Zoo Daily Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    print("[Model Zoo] model =", zoo_model_name)
    print("[Model Zoo] rolling-window prediction is used; foundation model weights are not changed.")

    feature_data, raw_data, _, _ = prepare_latest_feature_data(
        token,
        include_news_features=False,
        sync_news_db=False,
        fetch_workers=fetch_workers,
    )
    ok, message = validate_zoo_backend_environment(zoo_model_name)
    if not ok:
        return keep_existing_ranking_when_prediction_unavailable(
            model_backend=model_backend,
            zoo_model_name=zoo_model_name,
            message=message,
            raw_data=raw_data,
            feature_data=feature_data,
        )
    print("[Model Zoo Preflight]", message)

    fine_tune_report = {
        "fine_tuned": False,
        "reason": "model_zoo_daily_update_predict_only",
    }
    print("[FineTune] skipped: model zoo daily update uses predict-only mode.")

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
        "rolling_train_supported": False,
        "rolling_training_mode": "predict_only_no_weight_update",
        "model_feature_source": "kline_alpha158_only",
        "news_used_by_model": False,
        "news_synced_for_agent": False,
        "rolling_fine_tune_performed": fine_tune_report.get("fine_tuned", False),
        "rolling_fine_tune_reason": fine_tune_report.get("reason", "no_fine_tune_attempted"),
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


def dft_unet_external_daily_update(
    token: str,
    checkpoint_path: str | None = None,
    fetch_workers: int | None = None,
):
    ensure_dirs()

    print("=" * 80)
    print("[External DFT_UNET Daily Update Start]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    print("[External Model] backend = dft_unet_external")

    feature_data, raw_data, new_data_start_date, _ = prepare_latest_feature_data(
        token,
        include_news_features=False,
        sync_news_db=False,
        fetch_workers=fetch_workers,
    )
    feature_data, market_context_report = ensure_market_context_for_feature_data(
        feature_data=feature_data,
        token=token,
    )
    feature_data.to_csv(LATEST_FEATURE_DATA_PATH, index=False, encoding="utf-8-sig")

    base_checkpoint = checkpoint_path or DEFAULT_DFT_UNET_CHECKPOINT_PATH
    load_checkpoint = DFT_UNET_LATEST_MODEL_PATH if os.path.exists(DFT_UNET_LATEST_MODEL_PATH) else base_checkpoint
    from external_models.dft_unet_adapter import DFTUNetAdapter

    adapter = DFTUNetAdapter(checkpoint_path=load_checkpoint, device="cpu").load()

    old_metrics = {}
    if os.path.exists(DFT_UNET_LATEST_METRICS_PATH):
        try:
            with open(DFT_UNET_LATEST_METRICS_PATH, "r", encoding="utf-8") as f:
                old_metrics = json.load(f)
        except Exception:
            old_metrics = {}

    fine_tune_report = {"fine_tuned": False, "reason": "not_attempted"}
    try:
        fine_tune_report = adapter.fine_tune(
            feature_data=feature_data,
            last_train_date=old_metrics.get("latest_data_date"),
            new_data_start_date=new_data_start_date,
            epochs=1,
            lr=1e-4,
            save_path=DFT_UNET_LATEST_MODEL_PATH,
        )
        print(f"[FineTune] result: {fine_tune_report}")
    except Exception as exc:
        fine_tune_report = {
            "fine_tuned": False,
            "reason": f"external_finetune_skipped: {type(exc).__name__}: {exc}",
        }
        print(f"[FineTune] skipped: {fine_tune_report['reason']}")

    ranking = adapter.predict(raw_data=raw_data, feature_data=feature_data)
    if "date" in ranking.columns and not ranking.empty:
        latest_date = pd.to_datetime(ranking["date"].iloc[0])
        ranking["prediction_date"] = (latest_date + pd.offsets.BDay(1)).strftime("%Y-%m-%d")
    ranking.to_csv(RANKING_LATEST_PATH, index=False, encoding="utf-8-sig")

    date_text = datetime.today().strftime("%Y%m%d")
    if "date" in ranking.columns and not ranking.empty:
        date_text = str(ranking["date"].iloc[0]).replace("-", "")[:8]

    dated_path = os.path.join(OUTPUT_DIR, f"ranking_{date_text}_dft_unet_external.csv")
    ranking.to_csv(dated_path, index=False, encoding="utf-8-sig")

    metrics = {
        "model_name": "dft_unet",
        "model_backend": DFT_UNET_BACKEND,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "update_type": "daily_external_model_update",
        "model_feature_source": "kline_alpha158_market_context_only",
        "news_used_by_model": False,
        "news_synced_for_agent": False,
        "rolling_train_supported": True,
        "rolling_training_mode": "external_finetune_if_labeled_samples_exist",
        "rolling_fine_tune_performed": bool(fine_tune_report.get("fine_tuned", False)),
        "rolling_fine_tune_reason": fine_tune_report.get("reason", ""),
        "new_labeled_samples": int(fine_tune_report.get("new_labeled_samples") or fine_tune_report.get("samples") or 0),
        "latest_data_date": fine_tune_report.get("train_end_date") or old_metrics.get("latest_data_date", ""),
        "latest_raw_date": str(pd.to_datetime(raw_data["date"].max()).date()) if not raw_data.empty else "",
        "prediction_signal_date": str(pd.to_datetime(ranking["date"].iloc[0]).date()) if not ranking.empty and "date" in ranking.columns else "",
        "prediction_date": str(ranking["prediction_date"].iloc[0]) if not ranking.empty and "prediction_date" in ranking.columns else "",
        "prediction_horizon": "next_trading_day_T_plus_1",
        "ranking_rows": int(len(ranking)),
        "checkpoint_path": str(adapter.checkpoint_path),
        "market_context": market_context_report,
        "fine_tune_report": fine_tune_report,
    }
    os.makedirs(os.path.dirname(DFT_UNET_LATEST_METRICS_PATH), exist_ok=True)
    with open(DFT_UNET_LATEST_METRICS_PATH, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    log_row = {
        "update_time": metrics["update_time"],
        "fine_tuned": metrics["rolling_fine_tune_performed"],
        "new_labeled_samples": metrics["new_labeled_samples"],
        "latest_data_date": metrics["latest_data_date"],
        "reason": metrics["rolling_fine_tune_reason"],
    }
    log_path = DFT_UNET_FINETUNE_LOG_PATH
    log_df = pd.DataFrame([log_row])
    if os.path.exists(log_path):
        try:
            old_log = pd.read_csv(log_path)
            log_df = pd.concat([old_log, log_df], ignore_index=True)
        except Exception:
            pass
    log_df.to_csv(log_path, index=False, encoding="utf-8-sig")

    print(f"[Save] latest ranking -> {RANKING_LATEST_PATH}")
    print(f"[Save] dated ranking -> {dated_path}")
    print(f"[Save] DFT_UNET metrics -> {DFT_UNET_LATEST_METRICS_PATH}")
    print("[Top 5]")
    print(ranking.head(5)[["rank", "code", "name", "raw_score", "up_prob", "score", "confidence", "risk_level"]])
    print("=" * 80)
    print("[External DFT_UNET Daily Update Finished]", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 80)
    return ranking, metrics


def parse_args(argv: list[str] | None = None):
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
        default=DEFAULT_EXTERNAL_MODEL_BACKEND,
        help="每日更新使用的模型库模型。",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        default="",
        help="DFT_UNET external checkpoint path.",
    )
    parser.add_argument(
        "--fetch-workers",
        type=int,
        default=None,
        help="Parallel workers for recent Tushare daily downloads. Default uses TUSHARE_DAILY_FETCH_WORKERS or 4.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = str(args.model_backend or DEFAULT_EXTERNAL_MODEL_BACKEND).strip()
    if is_zoo_backend(backend):
        model_zoo_daily_update(
            token=args.token,
            model_backend=backend,
            fetch_workers=args.fetch_workers,
        )
    elif backend == DFT_UNET_BACKEND:
        dft_unet_external_daily_update(
            token=args.token,
            checkpoint_path=args.checkpoint_path or DEFAULT_DFT_UNET_CHECKPOINT_PATH,
            fetch_workers=args.fetch_workers,
        )
    else:
        raise ValueError(f"Unsupported external backend for daily update: {backend}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
