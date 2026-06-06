from __future__ import annotations

from pathlib import Path

from .base import ExternalTimeSeriesModelAdapter


class GenericPyTorchAdapter(ExternalTimeSeriesModelAdapter):
    def load(self):
        try:
            import torch
        except Exception as exc:
            raise RuntimeError("Generic PyTorch adapter requires torch.") from exc

        if not self.local_path or not Path(self.local_path).exists():
            raise FileNotFoundError(f"checkpoint not found: {self.local_path}")

        # Only load tensor weights; do not execute arbitrary pickled objects.
        self.checkpoint = torch.load(self.local_path, map_location="cpu", weights_only=True)
        self.loaded = True
        return self

    def build_input(self, raw_data, feature_data=None):
        raise NotImplementedError("GenericPyTorchAdapter only provides safe checkpoint loading.")

    def predict(self, raw_data, feature_data=None):
        raise NotImplementedError("GenericPyTorchAdapter needs a project-specific model definition.")

    def to_ranking_frame(self, pred_df):
        raise NotImplementedError
