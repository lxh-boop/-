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


class TimesFMAdapter(ExternalTimeSeriesModelAdapter):
    def __init__(
        self,
        model_name: str = "timesfm_2_0_500m",
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
        self.model = None

    def load(self):
        try:
            import timesfm
        except Exception as exc:
            raise RuntimeError(
                "TimesFM cannot be loaded in the current Python environment. "
                "The available PyPI package depends on JAX/PAXML/Lingvo; "
                f"import error: {exc}"
            ) from exc

        model_source = str(
            self.local_path
            if self.local_path and Path(self.local_path).exists()
            else self.entry.hf_repo
        )
        try:
            if hasattr(timesfm, "TimesFmHparams") and hasattr(timesfm, "TimesFmCheckpoint"):
                self.model = timesfm.TimesFm(
                    hparams=timesfm.TimesFmHparams(
                        backend="cpu" if self.device == "cpu" else self.device,
                        per_core_batch_size=self.batch_size,
                        horizon_len=self.prediction_length,
                        context_len=self.context_length,
                    ),
                    checkpoint=timesfm.TimesFmCheckpoint(
                        huggingface_repo_id=self.entry.hf_repo,
                    ),
                )
            else:
                self.model = timesfm.TimesFm(
                    context_len=self.context_length,
                    horizon_len=self.prediction_length,
                    input_patch_len=32,
                    output_patch_len=128,
                    num_layers=20,
                    model_dims=1280,
                    per_core_batch_size=self.batch_size,
                    backend="cpu",
                )
                checkpoint_path = str(Path(model_source) / "checkpoints") if Path(model_source).exists() else None
                self.model.load_from_checkpoint(
                    checkpoint_path=checkpoint_path,
                    repo_id=self.entry.hf_repo,
                )
        except Exception as exc:
            raise RuntimeError(f"TimesFM model initialization failed: {exc}") from exc

        self.loaded = True
        return self

    def build_input(self, raw_data, feature_data=None):
        return self.normalize_raw_data(raw_data)

    def _predict_batch(self, contexts: list[np.ndarray]) -> np.ndarray:
        if not self.loaded:
            self.load()

        result = self.model.forecast(
            inputs=[np.asarray(ctx, dtype=np.float32) for ctx in contexts],
            freq=[0] * len(contexts),
        )
        mean_forecast = result[0] if isinstance(result, tuple) else result
        return compound_return_from_forecast(mean_forecast, horizon=self.prediction_length)

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
            raise RuntimeError("TimesFM did not find enough OHLCV history windows for prediction.")

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
