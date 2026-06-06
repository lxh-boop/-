from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score

from config import LABEL_RET_CLIP, MODEL_PRED_COL, MODEL_REG_LABEL_COL
from .base import BaseModelBackend


def _require_lightgbm():
    try:
        import lightgbm as lgb
    except Exception as exc:
        raise RuntimeError(
            "LightGBM 未安装，请先运行：pip install lightgbm"
        ) from exc
    return lgb


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        value = float(value)
        return value if np.isfinite(value) else None
    if pd.isna(value) if not isinstance(value, (list, dict, tuple)) else False:
        return None
    return value


class LightGBMBackend(BaseModelBackend):
    backend_name = "lightgbm"

    def __init__(
        self,
        n_estimators: int = 1000,
        learning_rate: float = 0.02,
        num_leaves: int = 31,
        max_depth: int = -1,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        reg_alpha: float = 1.0,
        reg_lambda: float = 5.0,
        random_state: int = 42,
        early_stopping_rounds: int = 100,
    ):
        self.params = {
            "n_estimators": n_estimators,
            "learning_rate": learning_rate,
            "num_leaves": num_leaves,
            "max_depth": max_depth,
            "subsample": subsample,
            "colsample_bytree": colsample_bytree,
            "reg_alpha": reg_alpha,
            "reg_lambda": reg_lambda,
            "random_state": random_state,
            "n_jobs": -1,
            "verbosity": -1,
        }
        self.early_stopping_rounds = early_stopping_rounds
        self.return_model = None
        self.rank_model = None
        self.classifier_model = None
        self.feature_cols: list[str] = []
        self.metrics: dict[str, Any] = {}

    @staticmethod
    def _make_x(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
        return (
            df[feature_cols]
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .astype(np.float32)
        )

    @staticmethod
    def _rmse(y_true, y_pred) -> float:
        return float(mean_squared_error(y_true, y_pred) ** 0.5)

    def fit(self, train_df: pd.DataFrame, valid_df: pd.DataFrame, feature_cols: list[str]):
        lgb = _require_lightgbm()

        self.feature_cols = list(feature_cols)
        x_train = self._make_x(train_df, self.feature_cols)
        x_valid = self._make_x(valid_df, self.feature_cols)

        y_ret_train = pd.to_numeric(train_df["future_5d_ret"], errors="coerce").clip(
            -LABEL_RET_CLIP,
            LABEL_RET_CLIP,
        )
        y_ret_valid = pd.to_numeric(valid_df["future_5d_ret"], errors="coerce").clip(
            -LABEL_RET_CLIP,
            LABEL_RET_CLIP,
        )
        y_rank_train = pd.to_numeric(train_df[MODEL_REG_LABEL_COL], errors="coerce")
        y_rank_valid = pd.to_numeric(valid_df[MODEL_REG_LABEL_COL], errors="coerce")
        y_cls_train = pd.to_numeric(train_df["future_5d_up"], errors="coerce").astype(int)
        y_cls_valid = pd.to_numeric(valid_df["future_5d_up"], errors="coerce").astype(int)

        callbacks = [
            lgb.early_stopping(self.early_stopping_rounds, verbose=False),
            lgb.log_evaluation(period=0),
        ]

        self.return_model = lgb.LGBMRegressor(
            objective="regression",
            **self.params,
        )
        self.return_model.fit(
            x_train,
            y_ret_train,
            eval_set=[(x_valid, y_ret_valid)],
            eval_metric="rmse",
            callbacks=callbacks,
        )

        self.rank_model = lgb.LGBMRegressor(
            objective="regression",
            **self.params,
        )
        self.rank_model.fit(
            x_train,
            y_rank_train,
            eval_set=[(x_valid, y_rank_valid)],
            eval_metric="rmse",
            callbacks=callbacks,
        )

        self.classifier_model = lgb.LGBMClassifier(
            objective="binary",
            **self.params,
        )
        self.classifier_model.fit(
            x_train,
            y_cls_train,
            eval_set=[(x_valid, y_cls_valid)],
            eval_metric="binary_logloss",
            callbacks=callbacks,
        )

        valid_pred = self.predict(valid_df, self.feature_cols)
        pred_cls = (valid_pred["up_prob"] >= 0.5).astype(int)

        try:
            auc = roc_auc_score(y_cls_valid, valid_pred["up_prob"])
        except Exception:
            auc = np.nan

        self.metrics = {
            "backend_name": self.backend_name,
            "feature_count": len(self.feature_cols),
            "regression_target": "future_5d_ret",
            "rank_proxy_target": MODEL_REG_LABEL_COL,
            "classification_target": "future_5d_up",
            "valid_return_rmse": self._rmse(y_ret_valid, valid_pred["pred_5d_ret"]),
            "valid_rank_rmse": self._rmse(y_rank_valid, valid_pred["raw_score"]),
            "valid_accuracy": float(accuracy_score(y_cls_valid, pred_cls)),
            "valid_auc": float(auc) if np.isfinite(auc) else None,
            "params": dict(self.params),
            "early_stopping_rounds": int(self.early_stopping_rounds),
        }
        return self

    def predict(self, df: pd.DataFrame, feature_cols: list[str] | None = None) -> pd.DataFrame:
        if self.return_model is None or self.classifier_model is None:
            raise RuntimeError("LightGBMBackend 尚未加载或训练。")

        cols = list(feature_cols or self.feature_cols)
        x = self._make_x(df, cols)
        pred_ret = self.return_model.predict(x)

        if self.rank_model is not None:
            raw_score = self.rank_model.predict(x)
        else:
            raw_score = pred_ret

        if hasattr(self.classifier_model, "predict_proba"):
            up_prob = self.classifier_model.predict_proba(x)[:, 1]
        else:
            up_prob = np.full(len(df), np.nan)

        out = pd.DataFrame(
            {
                "pred_5d_ret": pred_ret,
                "raw_score": raw_score,
                MODEL_PRED_COL: raw_score,
                "up_prob": up_prob,
            },
            index=df.index,
        )
        return out

    def save(self, save_dir):
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "backend_name": self.backend_name,
            "feature_cols": self.feature_cols,
            "params": self.params,
            "early_stopping_rounds": self.early_stopping_rounds,
            "return_model": self.return_model,
            "rank_model": self.rank_model,
            "classifier_model": self.classifier_model,
            "metrics": self.metrics,
        }
        joblib.dump(payload, save_dir / "lightgbm_backend.pkl")
        (save_dir / "metrics.json").write_text(
            json.dumps(_to_jsonable(self.metrics), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return save_dir

    def load(self, save_dir):
        payload = joblib.load(Path(save_dir) / "lightgbm_backend.pkl")
        self.feature_cols = list(payload.get("feature_cols", []))
        self.params = dict(payload.get("params", self.params))
        self.early_stopping_rounds = int(
            payload.get("early_stopping_rounds", self.early_stopping_rounds)
        )
        self.return_model = payload.get("return_model")
        self.rank_model = payload.get("rank_model")
        self.classifier_model = payload.get("classifier_model")
        self.metrics = dict(payload.get("metrics", {}))
        return self
