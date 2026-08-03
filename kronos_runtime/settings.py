from __future__ import annotations

import os
from pathlib import Path
from typing import Any


KRONOS_BACKEND = "kronos_mini"
KRONOS_MODEL_NAME = "kronos_mini"
KRONOS_MODEL_VERSION = "hybrid_2017_20260730_causal_hit_rate"
KRONOS_RANKING_ORIENTATION = "causal_stock_hit_rate_descending"
KRONOS_HYBRID_RUN_ID = "hybrid_2017_step10_2026_daily_epoch3"
KRONOS_LATEST_CUTOFF = "20260730"
KRONOS_TRAINING_PENALTY = {
    "top20_false_positive": 4.0,
    "top15_false_positive": 6.0,
    "top10_non_positive": 9.0,
    "top5_non_positive": 12.0,
    "top10_loss_below_2pct": 16.0,
}
KRONOS_TARGET_VALIDATION = {
    "valid_test_days": 2049,
    "test_start_date": "2018-02-14",
    "test_end_date": "2026-07-30",
    "train_end_date": "2026-07-22",
    "epochs_per_update": 3,
    "rolling_update_rule": "2018-2025每10个交易日，2026起每个交易日",
    "label_rule": "real_return > 0 on the exact next trading day",
    "ranking_rule": "predicted_up_then_causal_stock_hit_rate_then_predicted_return",
    "stock_hit_rate_prior_mean": 0.5,
    "stock_hit_rate_prior_strength": 5.0,
    "universe_next_day_up_probability": 0.466596288675616,
    "top5_next_day_up_probability": 0.48657881893606636,
    "top10_next_day_up_probability": 0.48848218643240604,
    "top15_next_day_up_probability": 0.4870668618838458,
    "top5_lift_vs_universe": 0.01998253026045043,
    "top10_lift_vs_universe": 0.021885897756790097,
    "top15_lift_vs_universe": 0.02047057320822982,
    "top5_daily_mean_return": 0.0005507924998280623,
    "top10_daily_mean_return": 0.000543949722147752,
    "top15_daily_mean_return": 0.0005738298019085285,
    "all_topk_above_universe": True,
    "selection_period_all_topk_above_universe": True,
    "forward_2026_all_topk_above_universe": True,
}


def _default_lab_root() -> Path:
    if os.name == "nt":
        return Path(r"D:\google\kronos_model_lab")
    return Path("/kronos_model_lab")


def lab_root() -> Path:
    return Path(os.environ.get("KRONOS_LAB_ROOT") or _default_lab_root()).expanduser()


def hybrid_run_root() -> Path:
    return lab_root() / "outputs" / "hybrid_finetune" / KRONOS_HYBRID_RUN_ID


def model_dir() -> Path:
    configured = str(os.environ.get("KRONOS_MODEL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return hybrid_run_root() / "models" / KRONOS_LATEST_CUTOFF


def predictor_dir() -> Path:
    configured = str(os.environ.get("KRONOS_PREDICTOR_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return lab_root() / "models" / "pretrained" / "Kronos-mini"


def tokenizer_dir() -> Path:
    configured = str(os.environ.get("KRONOS_TOKENIZER_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return lab_root() / "models" / "pretrained" / "Kronos-Tokenizer-2k"


def market_panel_path() -> Path:
    return lab_root() / "data" / "processed" / "market_panel.parquet"


def validation_predictions_path() -> Path:
    return hybrid_run_root() / "causal_stock_hit_rate_ranking" / "selection_predictions.parquet"


def test_predictions_path() -> Path:
    return hybrid_run_root() / "causal_stock_hit_rate_ranking" / "forward_predictions.parquet"


def validation_report_path() -> Path:
    return hybrid_run_root() / "causal_stock_hit_rate_ranking" / "report.json"


def validate_kronos_assets() -> dict[str, Any]:
    paths = {
        "lab_root": lab_root(),
        "model_dir": model_dir(),
        "predictor_dir": predictor_dir(),
        "tokenizer_dir": tokenizer_dir(),
        "market_panel": market_panel_path(),
        "validation_predictions": validation_predictions_path(),
        "test_predictions": test_predictions_path(),
        "validation_report": validation_report_path(),
    }
    missing = [name for name, path in paths.items() if not path.exists()]
    if missing:
        details = ", ".join(f"{name}={paths[name]}" for name in missing)
        raise FileNotFoundError(f"Kronos 运行资产缺失：{details}")
    return {
        "ready": True,
        "backend": KRONOS_BACKEND,
        "model_name": KRONOS_MODEL_NAME,
        "model_version": KRONOS_MODEL_VERSION,
        "ranking_orientation": KRONOS_RANKING_ORIENTATION,
        "training_false_positive_penalty": dict(KRONOS_TRAINING_PENALTY),
        "target_validation": dict(KRONOS_TARGET_VALIDATION),
        "paths": {name: str(path) for name, path in paths.items()},
    }
