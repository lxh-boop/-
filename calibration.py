from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss


class ProbabilityCalibrator:
    def __init__(
        self,
        method: str = "logistic",
        min_samples: int = 80,
        min_positive: int = 10,
        min_negative: int = 10,
    ):
        if method not in {"logistic", "isotonic", "auto"}:
            raise ValueError("method must be one of: logistic, isotonic, auto")

        self.method = method
        self.min_samples = int(min_samples)
        self.min_positive = int(min_positive)
        self.min_negative = int(min_negative)
        self.model = None
        self.calibrated = False
        self.fitted_method = "identity"
        self.report: dict = {
            "calibrated": False,
            "method": "identity",
            "reason": "not fitted",
        }

    @staticmethod
    def _to_array(values) -> np.ndarray:
        arr = pd.Series(values).replace([np.inf, -np.inf], np.nan).dropna().values
        return arr.astype(float)

    @staticmethod
    def _normalize_prob(values: np.ndarray) -> np.ndarray:
        values = values.astype(float)

        if values.size == 0:
            return values

        if np.nanmin(values) >= 0.0 and np.nanmax(values) <= 1.0:
            return np.clip(values, 1e-6, 1.0 - 1e-6)

        std = np.nanstd(values)

        if std < 1e-12:
            return np.full_like(values, 0.5, dtype=float)

        z = (values - np.nanmean(values)) / std
        return np.clip(1.0 / (1.0 + np.exp(-z)), 1e-6, 1.0 - 1e-6)

    def fit(self, y_true, raw_score_or_prob):
        df = pd.DataFrame(
            {
                "y": pd.Series(y_true),
                "x": pd.Series(raw_score_or_prob),
            }
        ).replace([np.inf, -np.inf], np.nan).dropna()

        if df.empty:
            self.report = {
                "calibrated": False,
                "method": "identity",
                "reason": "empty calibration data",
            }
            return self

        y = df["y"].astype(int).values
        x = df["x"].astype(float).values
        x_prob = self._normalize_prob(x)

        n_samples = int(len(y))
        positives = int(y.sum())
        negatives = int(n_samples - positives)

        if (
            n_samples < self.min_samples
            or positives < self.min_positive
            or negatives < self.min_negative
        ):
            self.report = {
                "calibrated": False,
                "method": "identity",
                "reason": (
                    "not enough labeled samples or class balance "
                    f"(samples={n_samples}, pos={positives}, neg={negatives})"
                ),
                "samples": n_samples,
                "positive": positives,
                "negative": negatives,
            }
            return self

        method = self.method

        if method == "auto":
            method = "isotonic" if n_samples >= 300 else "logistic"

        try:
            if method == "isotonic":
                model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
                model.fit(x_prob, y)
                pred = np.clip(model.predict(x_prob), 1e-6, 1.0 - 1e-6)
            else:
                model = LogisticRegression(max_iter=1000)
                model.fit(x_prob.reshape(-1, 1), y)
                pred = np.clip(model.predict_proba(x_prob.reshape(-1, 1))[:, 1], 1e-6, 1.0 - 1e-6)

            self.model = model
            self.calibrated = True
            self.fitted_method = method
            self.report = {
                "calibrated": True,
                "method": method,
                "samples": n_samples,
                "positive": positives,
                "negative": negatives,
                "brier": float(brier_score_loss(y, pred)),
                "log_loss": float(log_loss(y, pred, labels=[0, 1])),
            }
        except Exception as exc:
            self.model = None
            self.calibrated = False
            self.fitted_method = "identity"
            self.report = {
                "calibrated": False,
                "method": "identity",
                "reason": f"fit failed: {type(exc).__name__}: {exc}",
                "samples": n_samples,
                "positive": positives,
                "negative": negatives,
            }

        return self

    def predict_proba(self, raw_score_or_prob):
        series = pd.Series(raw_score_or_prob)
        values = series.replace([np.inf, -np.inf], np.nan).astype(float).values
        mask = ~np.isnan(values)
        out = np.full(values.shape, 0.5, dtype=float)

        if mask.any():
            x_prob = self._normalize_prob(values[mask])

            if self.calibrated and self.model is not None:
                if self.fitted_method == "isotonic":
                    pred = self.model.predict(x_prob)
                else:
                    pred = self.model.predict_proba(x_prob.reshape(-1, 1))[:, 1]
                out[mask] = pred
            else:
                out[mask] = x_prob

        return np.clip(out, 1e-6, 1.0 - 1e-6)

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        return path

    @classmethod
    def load(cls, path):
        return joblib.load(path)

    def to_report_json(self) -> str:
        return json.dumps(self.report, ensure_ascii=False, indent=2)
