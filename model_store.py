import json
import os
import shutil
from datetime import datetime

import joblib
import torch

from config import MODEL_DIR, METRICS_PATH
from torch_models import Alpha158MLP


def get_model_root(model_name: str):
    return os.path.join(MODEL_DIR, model_name)


def get_latest_dir(model_name: str):
    return os.path.join(get_model_root(model_name), "latest")


def get_version_dir(model_name: str, version: str):
    return os.path.join(get_model_root(model_name), version)


def save_torch_model_bundle(
    model_name: str,
    model,
    scaler,
    feature_cols,
    metrics: dict,
):
    model_name = model_name.lower().strip()
    version = datetime.now().strftime("%Y%m%d_%H%M%S")

    model_root = get_model_root(model_name)
    version_dir = get_version_dir(model_name, version)
    latest_dir = get_latest_dir(model_name)

    os.makedirs(version_dir, exist_ok=True)

    bundle = {
        "model_name": model_name,
        "version": version,
        "model_state_dict": model.state_dict(),
        "model_config": model.model_config,
        "scaler": scaler,
        "feature_cols": feature_cols,
        "metrics": metrics,
    }

    bundle_path = os.path.join(version_dir, "torch_model_bundle.pt")
    torch.save(bundle, bundle_path)

    metrics_path = os.path.join(version_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    if os.path.exists(latest_dir):
        shutil.rmtree(latest_dir)

    shutil.copytree(version_dir, latest_dir)

    latest_info = {
        "model_name": model_name,
        "latest_version": version,
        "latest_dir": latest_dir,
        "bundle_path": os.path.join(latest_dir, "torch_model_bundle.pt"),
    }

    latest_info_path = os.path.join(model_root, "latest_info.json")
    with open(latest_info_path, "w", encoding="utf-8") as f:
        json.dump(latest_info, f, ensure_ascii=False, indent=2)

    joblib.dump(metrics, METRICS_PATH)

    print(f"[Save] torch model bundle -> {bundle_path}")
    print(f"[Save] latest torch model -> {latest_dir}")

    return latest_info


def load_torch_model_bundle(model_name: str, version: str = "latest", device=None):
    model_name = model_name.lower().strip()

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if version == "latest":
        model_dir = get_latest_dir(model_name)
    else:
        model_dir = get_version_dir(model_name, version)

    bundle_path = os.path.join(model_dir, "torch_model_bundle.pt")

    if not os.path.exists(bundle_path):
        raise FileNotFoundError(
            f"没有找到模型文件：{bundle_path}\n"
            f"请先运行：python train_model.py --token 你的TushareToken"
        )

    try:
        bundle = torch.load(bundle_path, map_location=device, weights_only=False)
    except TypeError:
        bundle = torch.load(bundle_path, map_location=device)

    model_config = bundle["model_config"]

    model = Alpha158MLP(
        input_dim=model_config["input_dim"],
        hidden_dims=model_config["hidden_dims"],
        dropout=model_config["dropout"],
    )

    model.load_state_dict(bundle["model_state_dict"])
    model = model.to(device)
    model.eval()

    return {
        "model_name": bundle["model_name"],
        "version": bundle["version"],
        "model": model,
        "scaler": bundle["scaler"],
        "feature_cols": bundle["feature_cols"],
        "metrics": bundle["metrics"],
    }


def list_model_versions(model_name: str):
    model_name = model_name.lower().strip()
    model_root = get_model_root(model_name)

    if not os.path.exists(model_root):
        return []

    versions = []

    for item in os.listdir(model_root):
        item_path = os.path.join(model_root, item)

        if item == "latest":
            continue

        if os.path.isdir(item_path):
            versions.append(item)

    return sorted(versions)