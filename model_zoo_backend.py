from __future__ import annotations

from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd

from confidence_scoring import add_confidence_scores
from model_zoo.metadata import get_model_metadata
from model_zoo.registry import get_model_entry, list_model_entries
from ranking_schema import normalize_ranking_columns, validate_ranking_schema
from risk_scoring import add_risk_scores


MODEL_ZOO_BACKEND_PREFIX = "zoo:"
ZOO_OPTIONAL_DEPENDENCIES = {
    "chronos": (
        "chronos",
        "Chronos 适配器需要 chronos-forecasting，请先运行：pip install chronos-forecasting",
    ),
    "timesfm": (
        "timesfm",
        "TimesFM 适配器需要 timesfm 及其 JAX 相关依赖；建议使用独立 Python 环境安装。",
    ),
    "moment": (
        "momentfm",
        "MOMENT 适配器需要 momentfm，请先安装 MOMENT 相关依赖。",
    ),
    "moirai": (
        "uni2ts",
        "Moirai 适配器需要 uni2ts；Windows/Python 3.12 下建议使用独立 Python 3.10/3.11 环境。",
    ),
}
ZOO_ADAPTER_CLASSES = {
    "chronos": ("model_zoo.adapters.chronos_adapter", "ChronosAdapter"),
    "timesfm": ("model_zoo.adapters.timesfm_adapter", "TimesFMAdapter"),
    "moment": ("model_zoo.adapters.moment_adapter", "MOMENTAdapter"),
    "moirai": ("model_zoo.adapters.moirai_adapter", "MoiraiAdapter"),
}


def make_zoo_backend_name(model_name: str) -> str:
    entry = get_model_entry(model_name)
    return f"{MODEL_ZOO_BACKEND_PREFIX}{entry.name}"


def is_zoo_backend(model_backend: str | None) -> bool:
    return str(model_backend or "").startswith(MODEL_ZOO_BACKEND_PREFIX)


def zoo_model_name_from_backend(model_backend: str) -> str:
    return str(model_backend).split(":", 1)[1]


def list_downloaded_zoo_model_names() -> list[str]:
    names: list[str] = []
    for entry in list_model_entries():
        meta = get_model_metadata(entry.name) or {}
        if meta.get("status") == "downloaded":
            names.append(entry.name)
    return names


def validate_zoo_backend_environment(model_name: str) -> tuple[bool, str]:
    entry = get_model_entry(model_name)
    meta = get_model_metadata(entry.name) or {}
    if meta.get("status") != "downloaded":
        return (
            False,
            f"{entry.name} 尚未下载。请先运行：python -m model_zoo.downloader --model {entry.name}",
        )

    local_path = Path(meta.get("local_path") or entry.local_path)
    if not local_path.exists():
        return False, f"{entry.name} 的本地模型目录不存在：{local_path}"

    dependency = ZOO_OPTIONAL_DEPENDENCIES.get(entry.adapter)
    if dependency:
        module_name, message = dependency
        try:
            __import__(module_name)
        except Exception as exc:
            return False, f"{message}。当前导入错误：{type(exc).__name__}: {exc}"

    return True, f"{entry.name} 模型文件和依赖检查通过。"


def load_zoo_adapter(
    model_name: str,
    device: str = "cpu",
    context_length: int = 64,
    batch_size: int = 64,
):
    ok, message = validate_zoo_backend_environment(model_name)
    if not ok:
        raise RuntimeError(message)

    entry = get_model_entry(model_name)
    meta = get_model_metadata(entry.name) or {}
    local_path = meta.get("local_path") or entry.local_path
    adapter_def = ZOO_ADAPTER_CLASSES.get(entry.adapter)
    if not adapter_def:
        raise RuntimeError(f"{entry.name} adapter is not registered.")

    module_name, class_name = adapter_def
    try:
        adapter_cls = getattr(import_module(module_name), class_name)
    except Exception as exc:
        raise RuntimeError(
            f"{entry.name} adapter could not be loaded: {type(exc).__name__}: {exc}"
        ) from exc

    return adapter_cls(
        model_name=entry.name,
        local_path=local_path,
        device=device,
        context_length=context_length,
        batch_size=batch_size,
    ).load()


def _merge_feature_columns(pred: pd.DataFrame, feature_data: pd.DataFrame) -> pd.DataFrame:
    if feature_data is None or feature_data.empty:
        return pred

    merge_cols = [
        "date",
        "code",
        "pct_chg",
        "day_ret",
        "t1_ret",
        "t1_up",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
        "future_5d_ret",
    ]
    available = [col for col in merge_cols if col in feature_data.columns]
    if "date" not in available or "code" not in available:
        return pred

    features = feature_data[available].copy()
    features["date"] = pd.to_datetime(features["date"])
    features["code"] = features["code"].astype(str).str.zfill(6)
    features = features.drop_duplicates(["date", "code"], keep="last")

    out = pred.copy()
    out["date"] = pd.to_datetime(out["date"])
    out["code"] = out["code"].astype(str).str.zfill(6)
    drop_cols = [col for col in available if col not in {"date", "code"} and col in out.columns]
    if drop_cols:
        out = out.drop(columns=drop_cols)
    return out.merge(features, on=["date", "code"], how="left")


def predict_zoo_scores_for_dates(
    model_name: str,
    raw_data: pd.DataFrame,
    feature_data: pd.DataFrame,
    prediction_dates: list,
    device: str = "cpu",
    context_length: int = 64,
    batch_size: int = 64,
) -> pd.DataFrame:
    adapter = load_zoo_adapter(
        model_name=model_name,
        device=device,
        context_length=context_length,
        batch_size=batch_size,
    )
    pred = adapter.predict_windows(
        raw_data=raw_data,
        feature_data=feature_data,
        prediction_dates=prediction_dates,
        min_context=min(32, int(context_length)),
    )
    pred = _merge_feature_columns(pred, feature_data)
    pred["model_name"] = get_model_entry(model_name).name
    pred["model_backend"] = make_zoo_backend_name(model_name)
    if "pred_score" not in pred.columns:
        pred["pred_score"] = pred["raw_score"] if "raw_score" in pred.columns else pred["pred_5d_ret"]
    if "up_prob" not in pred.columns:
        pred["up_prob"] = pred.groupby("date")["pred_score"].rank(pct=True).clip(0.01, 0.99)
    if "score" not in pred.columns:
        pred["score"] = pred.groupby("date")["pred_score"].rank(pct=True)
    return pred.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)


def make_zoo_latest_ranking(
    model_name: str,
    raw_data: pd.DataFrame,
    feature_data: pd.DataFrame,
    device: str = "cpu",
    context_length: int = 64,
    batch_size: int = 64,
) -> pd.DataFrame:
    latest_date = pd.to_datetime(raw_data["date"].max())
    pred = predict_zoo_scores_for_dates(
        model_name=model_name,
        raw_data=raw_data,
        feature_data=feature_data,
        prediction_dates=[latest_date],
        device=device,
        context_length=context_length,
        batch_size=batch_size,
    )
    out = pred[pd.to_datetime(pred["date"]) == latest_date].copy()
    if out.empty:
        raise RuntimeError(f"{model_name} did not produce predictions for {latest_date.date()}.")

    if "raw_score" not in out.columns:
        out["raw_score"] = out["pred_5d_ret"]
    out["up_prob_calibrated"] = out["up_prob"].clip(0.01, 0.99)
    out["calibrated"] = False
    out["calibration_method"] = "cross_sectional_rank_fallback"
    out["score"] = out["raw_score"].rank(pct=True)
    out["model_name"] = get_model_entry(model_name).name
    out["prediction_date"] = (latest_date + pd.offsets.BDay(1)).strftime("%Y-%m-%d")

    out = add_risk_scores(out)
    out = add_confidence_scores(out, calibration_report={"calibrated": False, "method": "none"})
    out = out.sort_values("score", ascending=False).reset_index(drop=True)
    out.insert(0, "rank", np.arange(1, len(out) + 1))
    out = normalize_ranking_columns(out)

    output_cols = [
        "rank",
        "date",
        "code",
        "name",
        "close",
        "pct_chg",
        "pred_5d_ret",
        "raw_score",
        "up_prob",
        "up_prob_calibrated",
        "calibrated",
        "calibration_method",
        "score",
        "confidence_score",
        "confidence",
        "confidence_detail",
        "risk_score",
        "risk_level",
        "risk_detail",
        "model_name",
        "ret_5",
        "ret_20",
        "vol_20",
        "drawdown_20",
        "prediction_date",
    ]
    out = out[[col for col in output_cols if col in out.columns]].copy()
    validate_ranking_schema(out)
    return out


def downloaded_zoo_backends() -> dict[str, str]:
    return {
        f"Model Zoo - {name}": make_zoo_backend_name(name)
        for name in list_downloaded_zoo_model_names()
    }


def registered_zoo_backends() -> dict[str, str]:
    return {
        f"Model Zoo - {entry.name}": make_zoo_backend_name(entry.name)
        for entry in list_model_entries()
    }
