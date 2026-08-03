from __future__ import annotations

import os
from pathlib import Path
from typing import Any


KRONOS_BACKEND = "kronos_mini"
KRONOS_MODEL_NAME = "kronos_mini"
KRONOS_MODEL_VERSION = "stock_hit_rate_order_20260520_epoch2"
KRONOS_RANKING_ORIENTATION = "ascending"
KRONOS_TRAINING_PENALTY = {
    "top20_false_positive": 4.0,
    "top15_false_positive": 6.0,
    "top10_non_positive": 9.0,
    "top5_non_positive": 12.0,
    "top10_loss_below_2pct": 16.0,
}
KRONOS_TARGET_VALIDATION = {
    "valid_test_days": 20,
    "test_start_date": "2026-07-03",
    "test_end_date": "2026-07-30",
    "train_end_date": "2026-05-20",
    "best_epoch": 2,
    "label_rule": "real_return > 0 on the exact next trading day",
    "universe_next_day_up_probability": 0.5251084672225612,
    "top5_next_day_up_probability": 0.46,
    "top10_next_day_up_probability": 0.475,
    "top15_next_day_up_probability": 0.48,
    "top5_lift_vs_universe": -0.06510846722256125,
    "top10_lift_vs_universe": -0.05010846722256129,
    "top15_lift_vs_universe": -0.04510846722256123,
    "top5_daily_mean_return": -0.00873534348824044,
    "top10_daily_mean_return": -0.007937000461786022,
    "top15_daily_mean_return": -0.008382750010835782,
    "all_topk_above_universe": False,
}


def _default_lab_root() -> Path:
    if os.name == "nt":
        return Path(r"D:\google\kronos_model_lab")
    return Path("/kronos_model_lab")


def lab_root() -> Path:
    return Path(os.environ.get("KRONOS_LAB_ROOT") or _default_lab_root()).expanduser()


def model_dir() -> Path:
    configured = str(os.environ.get("KRONOS_MODEL_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return lab_root() / "outputs" / "target_mode" / "target_full_recent_v1" / "model"


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
    return (
        lab_root()
        / "outputs"
        / "target_mode"
        / "target_full_recent_v1"
        / "model"
        / "epochs"
        / "epoch_002"
        / "validation_predictions.parquet"
    )


def test_predictions_path() -> Path:
    return (
        lab_root()
        / "outputs"
        / "target_mode"
        / "target_full_recent_v1"
        / "predictions.parquet"
    )


def validate_kronos_assets() -> dict[str, Any]:
    paths = {
        "lab_root": lab_root(),
        "model_dir": model_dir(),
        "predictor_dir": predictor_dir(),
        "tokenizer_dir": tokenizer_dir(),
        "market_panel": market_panel_path(),
        "validation_predictions": validation_predictions_path(),
        "test_predictions": test_predictions_path(),
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
