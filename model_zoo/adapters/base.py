from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


class ExternalTimeSeriesModelAdapter:
    model_name: str = "external_time_series_model"

    def __init__(
        self,
        model_name: str,
        local_path: str | Path | None = None,
        device: str = "cpu",
        prediction_length: int = 5,
        context_length: int = 64,
    ):
        self.model_name = model_name
        self.local_path = Path(local_path) if local_path else None
        self.device = device
        self.prediction_length = int(prediction_length)
        self.context_length = int(context_length)
        self.loaded = False

    def load(self):
        raise NotImplementedError

    def build_input(self, raw_data, feature_data=None):
        raise NotImplementedError

    def predict(self, raw_data, feature_data=None):
        raise NotImplementedError

    def to_ranking_frame(self, pred_df):
        raise NotImplementedError

    @staticmethod
    def normalize_raw_data(raw_data: pd.DataFrame) -> pd.DataFrame:
        if raw_data is None or raw_data.empty:
            raise RuntimeError("外部时间序列模型需要非空 raw_data。")

        data = raw_data.copy()
        data["date"] = pd.to_datetime(data["date"])
        data["code"] = data["code"].astype(str).str.zfill(6)
        if "name" not in data.columns:
            data["name"] = data["code"]
        data = data.dropna(subset=["date", "code", "close"])
        data["close"] = pd.to_numeric(data["close"], errors="coerce")
        data = data.dropna(subset=["close"])
        return data.sort_values(["code", "date"]).reset_index(drop=True)

    @staticmethod
    def attach_score_columns(pred_df: pd.DataFrame) -> pd.DataFrame:
        out = pred_df.copy()
        if "raw_score" not in out.columns:
            out["raw_score"] = out["pred_5d_ret"]
        if "score" not in out.columns:
            out["score"] = out.groupby("date")["raw_score"].rank(pct=True)
        if "up_prob" not in out.columns:
            out["up_prob"] = out.groupby("date")["raw_score"].rank(pct=True).clip(0.01, 0.99)
        out["model_name"] = out.get("model_name", "")
        out["model_name"] = out["model_name"].replace("", np.nan).fillna("external_time_series_model")
        return out

    @staticmethod
    def merge_future_labels(pred_df: pd.DataFrame, feature_data: pd.DataFrame | None) -> pd.DataFrame:
        if feature_data is None or feature_data.empty or "future_5d_ret" not in feature_data.columns:
            return pred_df

        labels = feature_data[["date", "code", "future_5d_ret"]].copy()
        labels["date"] = pd.to_datetime(labels["date"])
        labels["code"] = labels["code"].astype(str).str.zfill(6)
        labels = labels.drop_duplicates(["date", "code"], keep="last")

        out = pred_df.copy()
        out["date"] = pd.to_datetime(out["date"])
        out["code"] = out["code"].astype(str).str.zfill(6)
        if "future_5d_ret" in out.columns:
            out = out.drop(columns=["future_5d_ret"])
        return out.merge(labels, on=["date", "code"], how="left")
