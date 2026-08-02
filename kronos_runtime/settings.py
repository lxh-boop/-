from __future__ import annotations

import os
from pathlib import Path
from typing import Any


KRONOS_BACKEND = "kronos_mini"
KRONOS_MODEL_NAME = "kronos_mini"
KRONOS_MODEL_VERSION = "initial_recent_year_20260520"
KRONOS_TRAINING_PENALTY = {
    "top20_false_positive": 3.0,
    "top10_non_positive": 5.0,
    "top10_loss_below_2pct": 8.0,
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
    return lab_root() / "outputs" / "models" / "initial_recent_year_20260520"


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


def validate_kronos_assets() -> dict[str, Any]:
    paths = {
        "lab_root": lab_root(),
        "model_dir": model_dir(),
        "predictor_dir": predictor_dir(),
        "tokenizer_dir": tokenizer_dir(),
        "market_panel": market_panel_path(),
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
        "training_false_positive_penalty": dict(KRONOS_TRAINING_PENALTY),
        "paths": {name: str(path) for name, path in paths.items()},
    }
