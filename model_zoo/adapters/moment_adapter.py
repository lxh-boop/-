from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from model_zoo.metadata import get_model_metadata
from model_zoo.ohlcv_windows import (
    MULTIVARIATE_OHLCV_COLUMNS,
    build_windows,
    compound_return_from_forecast,
)
from model_zoo.registry import get_model_entry

from .base import ExternalTimeSeriesModelAdapter


class MOMENTAdapter(ExternalTimeSeriesModelAdapter):
    def __init__(
        self,
        model_name: str = "moment_small",
        local_path: str | Path | None = None,
        device: str = "cpu",
        prediction_length: int = 5,
        context_length: int = 64,
        batch_size: int = 32,
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
        self.mode = "forecast"

    def load(self):
        try:
            import torch
            from momentfm import MOMENTPipeline
        except Exception as exc:
            raise RuntimeError(
                "MOMENT adapter requires the optional package momentfm. "
                f"Import error: {exc}"
            ) from exc

        model_source = str(
            self.local_path
            if self.local_path and Path(self.local_path).exists()
            else self.entry.hf_repo
        )
        self.pipeline = MOMENTPipeline.from_pretrained(
            model_source,
            model_kwargs={"task_name": "reconstruction"},
            local_files_only=Path(model_source).exists(),
        )
        self.mode = "short_forecast"

        if hasattr(self.pipeline, "init"):
            self.pipeline.init()
        self.pipeline = self.pipeline.to(torch.device(self.device))
        self.pipeline.eval()
        self.loaded = True
        return self

    def build_input(self, raw_data, feature_data=None):
        return self.normalize_raw_data(raw_data)

    def _predict_batch(self, windows: list[np.ndarray]) -> np.ndarray:
        if not self.loaded:
            self.load()

        import torch

        # Windows are [context, channels]; MOMENT expects [batch, channels, context].
        arr = np.stack([w.T for w in windows]).astype(np.float32)
        x_enc = torch.tensor(arr, dtype=torch.float32, device=self.device)
        input_mask = torch.ones((x_enc.shape[0], x_enc.shape[-1]), dtype=torch.long, device=self.device)

        with torch.no_grad():
            outputs = self.pipeline.short_forecast(
                x_enc=x_enc,
                input_mask=input_mask,
                forecast_horizon=self.prediction_length,
            )

        forecast = getattr(outputs, "forecast", None)
        if forecast is None:
            raise RuntimeError("MOMENT did not return a forecast tensor.")
        forecast_np = forecast.detach().cpu().numpy()
        close_ret_forecast = forecast_np[:, 0, :]
        return compound_return_from_forecast(close_ret_forecast, horizon=self.prediction_length)

    def predict_windows(
        self,
        raw_data: pd.DataFrame,
        feature_data: pd.DataFrame | None = None,
        prediction_dates: list | None = None,
        min_context: int = 32,
        max_prediction_dates: int | None = None,
    ) -> pd.DataFrame:
        data = self.build_input(raw_data, feature_data)
        if prediction_dates is None:
            prediction_dates = list(data["date"].drop_duplicates().sort_values())
        prediction_dates = list(pd.to_datetime(prediction_dates))
        if max_prediction_dates:
            prediction_dates = prediction_dates[-int(max_prediction_dates):]

        batch = build_windows(
            raw_data=data,
            prediction_dates=prediction_dates,
            context_length=self.context_length,
            min_context=min_context,
            feature_columns=MULTIVARIATE_OHLCV_COLUMNS,
        )
        if not batch.windows:
            raise RuntimeError("MOMENT did not find enough OHLCV history windows for prediction.")

        preds: list[float] = []
        for start in range(0, len(batch.windows), self.batch_size):
            preds.extend(self._predict_batch(batch.windows[start : start + self.batch_size]).tolist())

        out = pd.DataFrame(batch.rows)
        out["pred_5d_ret"] = np.asarray(preds, dtype=float)
        out["raw_score"] = out["pred_5d_ret"]
        out["model_name"] = self.model_name
        out = self.attach_score_columns(out)
        out = self.merge_future_labels(out, feature_data)
        return out.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)

    def predict(self, raw_data, feature_data=None):
        data = self.build_input(raw_data, feature_data)
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
