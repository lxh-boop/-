from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from model_zoo.metadata import get_model_metadata
from model_zoo.ohlcv_windows import (
    UNIVARIATE_RETURN_COL,
    build_windows,
    compound_return_from_forecast,
)
from model_zoo.registry import get_model_entry

from .base import ExternalTimeSeriesModelAdapter


class ChronosAdapter(ExternalTimeSeriesModelAdapter):
    def __init__(
        self,
        model_name: str = "chronos_bolt_small",
        local_path: str | Path | None = None,
        device: str = "cpu",
        prediction_length: int = 5,
        context_length: int = 64,
        batch_size: int = 64,
    ):
        entry = get_model_entry(model_name)
        meta = get_model_metadata(entry.name) or {}
        resolved_path = local_path or meta.get("local_path") or entry.local_path
        super().__init__(
            model_name=entry.name,
            local_path=resolved_path,
            device=device,
            prediction_length=prediction_length,
            context_length=context_length,
        )
        self.entry = entry
        self.batch_size = int(batch_size)
        self.pipeline = None

    def load(self):
        try:
            import torch
            from chronos import BaseChronosPipeline
        except Exception as exc:
            raise RuntimeError(
                "Chronos 适配器需要 chronos-forecasting，请先运行：pip install chronos-forecasting"
            ) from exc

        model_source = str(self.local_path if self.local_path and Path(self.local_path).exists() else self.entry.hf_repo)
        try:
            self.pipeline = BaseChronosPipeline.from_pretrained(
                model_source,
                device_map=self.device,
                dtype=torch.float32,
            )
        except TypeError:
            self.pipeline = BaseChronosPipeline.from_pretrained(model_source)

        self.loaded = True
        return self

    def build_input(self, raw_data, feature_data=None):
        return build_windows(
            raw_data=raw_data,
            prediction_dates=[],
            context_length=self.context_length,
            min_context=min(32, self.context_length),
            feature_columns=[UNIVARIATE_RETURN_COL],
        )

    @staticmethod
    def _forecast_to_pred_ret(forecast) -> np.ndarray:
        arr = forecast.detach().cpu().numpy() if hasattr(forecast, "detach") else np.asarray(forecast)
        if arr.ndim == 3:
            # Works for both quantile and sample dimensions by taking the median path.
            future_ret = np.nanmedian(arr, axis=1)
        elif arr.ndim == 2:
            future_ret = arr
        else:
            future_ret = np.asarray(arr).reshape(1, -1)
        return compound_return_from_forecast(future_ret, horizon=5)

    def _predict_batch(self, contexts: list[np.ndarray]) -> np.ndarray:
        if not self.loaded:
            self.load()

        import torch

        tensors = [
            torch.tensor(np.asarray(ctx, dtype=np.float32), dtype=torch.float32)
            for ctx in contexts
        ]
        try:
            forecast = self.pipeline.predict(
                inputs=tensors,
                prediction_length=self.prediction_length,
            )
        except TypeError:
            forecast = self.pipeline.predict(
                context=tensors,
                prediction_length=self.prediction_length,
            )
        return self._forecast_to_pred_ret(forecast)

    def predict_windows(
        self,
        raw_data: pd.DataFrame,
        feature_data: pd.DataFrame | None = None,
        prediction_dates: list | None = None,
        min_context: int = 32,
        max_prediction_dates: int | None = None,
    ) -> pd.DataFrame:
        data = self.normalize_raw_data(raw_data)
        if prediction_dates is None:
            if feature_data is not None and not feature_data.empty and "future_5d_ret" in feature_data.columns:
                label_dates = (
                    feature_data.dropna(subset=["future_5d_ret"])["date"]
                    .pipe(pd.to_datetime)
                    .drop_duplicates()
                    .sort_values()
                )
                prediction_dates = list(label_dates)
            else:
                prediction_dates = list(data["date"].drop_duplicates().sort_values())

        prediction_dates = list(pd.to_datetime(prediction_dates))
        if max_prediction_dates:
            prediction_dates = prediction_dates[-int(max_prediction_dates):]
        batch = build_windows(
            raw_data=data,
            prediction_dates=prediction_dates,
            context_length=self.context_length,
            min_context=min_context,
            feature_columns=[UNIVARIATE_RETURN_COL],
        )
        contexts = [window[:, 0] for window in batch.windows]
        rows = batch.rows

        if not contexts:
            raise RuntimeError("Chronos 没有找到足够长度的历史窗口，无法预测。")

        preds: list[float] = []
        for start in range(0, len(contexts), self.batch_size):
            batch = contexts[start : start + self.batch_size]
            preds.extend(self._predict_batch(batch).tolist())

        out = pd.DataFrame(rows)
        out["pred_5d_ret"] = np.asarray(preds, dtype=float)
        out["raw_score"] = out["pred_5d_ret"]
        out["model_name"] = self.model_name
        out = self.attach_score_columns(out)
        out = self.merge_future_labels(out, feature_data)
        return out.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)

    def predict(self, raw_data, feature_data=None):
        data = self.normalize_raw_data(raw_data)
        latest_date = pd.to_datetime(data["date"].max())
        return self.predict_windows(
            raw_data=data,
            feature_data=feature_data,
            prediction_dates=[latest_date],
            min_context=min(32, self.context_length),
        )

    def to_ranking_frame(self, pred_df):
        out = pred_df.copy()
        latest_date = pd.to_datetime(out["date"]).max()
        out = out[pd.to_datetime(out["date"]) == latest_date].copy()
        out = out.sort_values("score", ascending=False).reset_index(drop=True)
        out.insert(0, "rank", np.arange(1, len(out) + 1))
        return out
