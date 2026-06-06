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


class MoiraiAdapter(ExternalTimeSeriesModelAdapter):
    def __init__(
        self,
        model_name: str = "moirai_small",
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
        self.predictor = None

    def load(self):
        try:
            from uni2ts.model.moirai import MoiraiForecast, MoiraiModule
        except Exception as exc:
            raise RuntimeError(
                "Moirai requires the optional package uni2ts. In this Windows/Python 3.12 "
                "environment pip installation failed while replacing scipy/torch DLLs. "
                "Use an isolated Python 3.10/3.11 environment for Moirai, or install uni2ts "
                f"successfully before enabling this backend. Import error: {exc}"
            ) from exc

        model_source = str(
            self.local_path
            if self.local_path and Path(self.local_path).exists()
            else self.entry.hf_repo
        )
        try:
            module = MoiraiModule.from_pretrained(model_source)
            forecast = MoiraiForecast(
                module=module,
                prediction_length=self.prediction_length,
                context_length=self.context_length,
                patch_size="auto",
                num_samples=100,
                target_dim=1,
                feat_dynamic_real_dim=0,
                past_feat_dynamic_real_dim=0,
            )
            self.predictor = forecast.create_predictor(batch_size=self.batch_size)
        except Exception as exc:
            raise RuntimeError(f"Moirai model initialization failed: {exc}") from exc

        self.loaded = True
        return self

    def build_input(self, raw_data, feature_data=None):
        return self.normalize_raw_data(raw_data)

    def _predict_batch(self, contexts: list[np.ndarray]) -> np.ndarray:
        if not self.loaded:
            self.load()

        from gluonts.dataset.common import ListDataset

        dataset = ListDataset(
            [
                {
                    "start": pd.Period("2000-01-01", freq="D"),
                    "target": np.asarray(ctx, dtype=np.float32),
                }
                for ctx in contexts
            ],
            freq="D",
        )
        forecasts = list(self.predictor.predict(dataset))
        values = []
        for forecast in forecasts:
            samples = getattr(forecast, "samples", None)
            if samples is not None:
                values.append(np.nanmedian(samples, axis=0))
            else:
                values.append(np.asarray(forecast.mean))
        return compound_return_from_forecast(np.asarray(values), horizon=self.prediction_length)

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
            feature_columns=[UNIVARIATE_RETURN_COL],
        )
        if not batch.windows:
            raise RuntimeError("Moirai did not find enough OHLCV history windows for prediction.")

        contexts = [window[:, 0] for window in batch.windows]
        preds: list[float] = []
        for start in range(0, len(contexts), self.batch_size):
            preds.extend(self._predict_batch(contexts[start : start + self.batch_size]).tolist())

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
