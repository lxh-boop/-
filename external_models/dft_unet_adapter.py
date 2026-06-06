from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from alpha158 import get_alpha158_feature_cols
from confidence_scoring import add_confidence_scores
from config import DEFAULT_DFT_UNET_CHECKPOINT_PATH
from inspect_external_model import inspect_checkpoint
from market_context import MARKET_CONTEXT_COLUMNS
from ranking_schema import normalize_ranking_columns, validate_ranking_schema
from risk_scoring import add_risk_scores


DFT_UNET_PROJECT_ROOT = Path(r"D:\paper_work\Unet_DFT")
MODEL_NAME = "dft_unet"
LEGACY_MODEL_NAME = "dft_unet_external"


class DFTUNetAdapter:
    def __init__(
        self,
        checkpoint_path: str | None = None,
        device: str = "cpu",
        model_name: str = MODEL_NAME,
    ):
        self.checkpoint_path = Path(checkpoint_path or DEFAULT_DFT_UNET_CHECKPOINT_PATH)
        self.device = device
        self.model_name = model_name
        self.model = None
        self.loaded = False
        self.summary: dict[str, Any] = {}
        self.args: dict[str, Any] = {}
        self.load_report: dict[str, Any] = {}

    @property
    def input_spec(self) -> dict[str, Any]:
        seq_len = int(self.args.get("seq_len", 8))
        d_feat = int(self.args.get("d_feat", 158))
        start = int(self.args.get("gate_input_start_index", 158))
        end = int(self.args.get("gate_input_end_index", 221))
        return {
            "shape": f"[N, {seq_len}, {end}]",
            "seq_len": seq_len,
            "stock_feature_count": d_feat,
            "market_context_count": max(0, end - start),
            "description": (
                "DFT_UNET expects a daily cross-section tensor. "
                "The first 158 columns are Alpha158 stock features and "
                "the next 63 columns are market context features."
            ),
        }

    def inspect(self) -> dict[str, Any]:
        report = inspect_checkpoint(str(self.checkpoint_path))
        report["summary_json_found"] = (self.checkpoint_path.parent / "summary.json").exists()
        try:
            summary = self._load_summary()
            report["experiment_model_name"] = summary.get("model_name")
            report["experiment_run_name"] = summary.get("run_name")
            report["best_epoch"] = summary.get("best_epoch")
            report["best_score"] = summary.get("best_score")
            report["input_spec"] = self._input_spec_from_args(summary.get("args", {}))
        except Exception as exc:
            report["summary_error"] = f"{type(exc).__name__}: {exc}"
        return report

    def load(self):
        if not self.checkpoint_path.exists():
            raise FileNotFoundError(f"DFT_UNET checkpoint not found: {self.checkpoint_path}")

        self.summary = self._load_summary()
        self.args = dict(self.summary.get("args") or {})

        if not DFT_UNET_PROJECT_ROOT.exists():
            raise RuntimeError(f"External DFT_UNET source directory not found: {DFT_UNET_PROJECT_ROOT}")

        project_root_text = str(DFT_UNET_PROJECT_ROOT)
        if project_root_text not in sys.path:
            sys.path.append(project_root_text)

        try:
            import torch
            from DFT_MSAD_UNet import DFT_MSAD_TIR_UNet
        except Exception as exc:
            raise RuntimeError(
                "Could not import DFT_MSAD_TIR_UNet from the external project. "
                f"Added sys.path={DFT_UNET_PROJECT_ROOT}. "
                f"Original error: {type(exc).__name__}: {exc}"
            ) from exc

        model = DFT_MSAD_TIR_UNet(**self._model_kwargs())
        state_dict = self._load_state_dict(torch)
        state_dict = self._patch_legacy_state_dict_keys(state_dict)

        missing, unexpected = model.load_state_dict(state_dict, strict=False)
        if missing or unexpected:
            raise RuntimeError(
                "DFT_UNET checkpoint does not match the model definition: "
                f"missing={missing[:20]}, unexpected={unexpected[:20]}"
            )

        model = model.to(self.device)
        model.eval()

        self.model = model
        self.loaded = True
        self.load_report = {
            "loaded": True,
            "checkpoint_path": str(self.checkpoint_path),
            "model_name": self.summary.get("model_name", "DFT_UNET"),
            "backend_model_name": self.model_name,
            "run_name": self.summary.get("run_name"),
            "best_epoch": self.summary.get("best_epoch"),
            "best_score": self.summary.get("best_score"),
            "input_spec": self.input_spec,
        }
        return self

    def build_input(
        self,
        raw_data: pd.DataFrame | None,
        feature_data: pd.DataFrame | None = None,
        prediction_dates: list | None = None,
        include_labels: bool = False,
        label_col: str | None = None,
    ) -> dict[str, Any]:
        if feature_data is None or feature_data.empty:
            raise RuntimeError("DFT_UNET input requires Alpha158 feature_data.")

        if not self.loaded:
            self.load()

        data = feature_data.copy()
        data["date"] = pd.to_datetime(data["date"])
        data["code"] = data["code"].astype(str).str.zfill(6)

        stock_cols = self._stock_feature_columns(data)
        market_cols = self._market_context_columns(data, stock_cols)
        seq_len = int(self.args.get("seq_len", 8))
        end = int(self.args.get("gate_input_end_index", 221))

        if len(stock_cols) < 158 or len(market_cols) < 63:
            raise RuntimeError(
                "DFT_UNET requires [N, 8, 221] input: 158 Alpha158 columns "
                f"and 63 market context columns. Current data has "
                f"Alpha158={len(stock_cols)}, market_context={len(market_cols)}."
            )

        if include_labels:
            label_col = label_col or self._default_label_column(data)
            if not label_col or label_col not in data.columns:
                raise RuntimeError(
                    "DFT_UNET fine-tuning requires a supervised label column. "
                    "Expected future_5d_score or future_5d_ret."
                )
        else:
            label_col = None

        if prediction_dates is None:
            prediction_date_set = None
        else:
            prediction_date_set = set(pd.to_datetime(prediction_dates))

        required_cols = stock_cols[:158] + market_cols[:63]
        daily_tensors: dict[pd.Timestamp, list[np.ndarray]] = {}
        daily_rows: dict[pd.Timestamp, list[dict[str, Any]]] = {}

        for _, group in data.groupby("code"):
            group = group.sort_values("date").reset_index(drop=True)
            if include_labels:
                label_mask = pd.to_numeric(group[label_col], errors="coerce").notna().to_numpy()
                if prediction_date_set is not None:
                    label_mask = label_mask & group["date"].isin(prediction_date_set).to_numpy()
                candidate_indices = np.flatnonzero(label_mask)
            elif prediction_date_set is None:
                valid_close = group["close"].notna().to_numpy()
                candidate_indices = np.flatnonzero(valid_close)
                candidate_indices = candidate_indices[-1:] if len(candidate_indices) else candidate_indices
            else:
                candidate_indices = np.flatnonzero(group["date"].isin(prediction_date_set).to_numpy())

            for idx in candidate_indices:
                if idx + 1 < seq_len:
                    continue

                window = group.iloc[idx + 1 - seq_len: idx + 1].copy()
                if len(window) < seq_len or window["close"].isna().any():
                    continue

                values = (
                    window[required_cols]
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0.0)
                    .astype(np.float32)
                    .values
                )
                if values.shape != (seq_len, end):
                    raise RuntimeError(f"DFT_UNET window shape mismatch: expected {(seq_len, end)}, got {values.shape}.")

                date_value = pd.to_datetime(group.iloc[idx]["date"])
                row = group.iloc[idx].to_dict()

                if include_labels:
                    label_value = pd.to_numeric(group.iloc[idx][label_col], errors="coerce")
                    if not np.isfinite(label_value):
                        continue
                    full_values = np.zeros((seq_len, end + 1), dtype=np.float32)
                    full_values[:, :end] = values
                    full_values[-1, -1] = float(label_value)
                    values_to_store = full_values
                else:
                    values_to_store = values

                daily_rows.setdefault(date_value, []).append(row)
                daily_tensors.setdefault(date_value, []).append(values_to_store)

        if not daily_tensors:
            purpose = "fine-tuning" if include_labels else "prediction"
            raise RuntimeError(f"No valid 8-day DFT_UNET windows were found for {purpose}.")

        return {
            "daily_tensors": daily_tensors,
            "daily_rows": daily_rows,
            "feature_columns": required_cols,
            "stock_feature_columns": stock_cols[:158],
            "market_context_columns": market_cols[:63],
            "label_col": label_col,
            "seq_len": seq_len,
            "input_dim": end,
            "include_labels": include_labels,
        }

    def predict(self, raw_data: pd.DataFrame, feature_data: pd.DataFrame | None = None) -> pd.DataFrame:
        built = self.build_input(raw_data=raw_data, feature_data=feature_data, include_labels=False)
        import torch

        output_frames = []
        for date_value in sorted(built["daily_tensors"]):
            x = torch.tensor(
                np.stack(built["daily_tensors"][date_value]),
                dtype=torch.float32,
                device=self.device,
            )
            with torch.no_grad():
                pred = self.model(torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0))
                pred = torch.nan_to_num(pred, nan=0.0, posinf=20.0, neginf=-20.0).clamp(-20.0, 20.0)

            scores = pred.detach().cpu().numpy().reshape(-1).astype(float)
            scores = scores * float(self.summary.get("prediction_sign", 1.0) or 1.0)
            daily_out = pd.DataFrame(built["daily_rows"][date_value])
            daily_out["pred_5d_ret"] = scores
            daily_out["raw_score"] = scores
            output_frames.append(daily_out)

        out = pd.concat(output_frames, ignore_index=True)
        out["code"] = out["code"].astype(str).str.zfill(6)
        out["score"] = out["raw_score"].rank(pct=True)
        out["up_prob"] = out["score"].clip(0.01, 0.99)
        out["up_prob_calibrated"] = out["up_prob"]
        out["calibrated"] = False
        out["calibration_method"] = "cross_sectional_rank_fallback"
        out["model_name"] = self.model_name

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
        ]
        out = out[[col for col in output_cols if col in out.columns]].copy()
        validate_ranking_schema(out)
        return out

    def predict_scores_for_windows(
        self,
        feature_data: pd.DataFrame,
        prediction_dates: list | None = None,
    ) -> pd.DataFrame:
        built = self.build_input(
            raw_data=None,
            feature_data=feature_data,
            prediction_dates=prediction_dates,
            include_labels=False,
        )
        import torch

        output_frames = []
        for date_value in sorted(built["daily_tensors"]):
            x = torch.tensor(
                np.stack(built["daily_tensors"][date_value]),
                dtype=torch.float32,
                device=self.device,
            )
            with torch.no_grad():
                pred = self.model(torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0))
                pred = torch.nan_to_num(pred, nan=0.0, posinf=20.0, neginf=-20.0).clamp(-20.0, 20.0)

            scores = pred.detach().cpu().numpy().reshape(-1).astype(float)
            scores = scores * float(self.summary.get("prediction_sign", 1.0) or 1.0)
            daily_out = pd.DataFrame(built["daily_rows"][date_value])
            daily_out["raw_score"] = scores
            output_frames.append(daily_out)

        out = pd.concat(output_frames, ignore_index=True)
        out["code"] = out["code"].astype(str).str.zfill(6)
        out["pred_score"] = out["raw_score"]
        out["score"] = out.groupby("date")["raw_score"].rank(pct=True)
        out["up_prob"] = out["score"].clip(0.01, 0.99)
        out["model_name"] = self.model_name
        return out.sort_values(["date", "score"], ascending=[True, False]).reset_index(drop=True)

    def state_dict(self) -> dict[str, Any]:
        if not self.loaded:
            self.load()
        return self.model.state_dict()

    def fine_tune(
        self,
        feature_data: pd.DataFrame,
        last_train_date: str | None = None,
        new_data_start_date=None,
        epochs: int = 3,
        lr: float = 1e-4,
        batch_size: int = 128,
        save_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if not self.loaded:
            self.load()

        data = feature_data.copy()
        data["date"] = pd.to_datetime(data["date"])
        label_col = self._default_label_column(data)
        if not label_col:
            return {
                "fine_tuned": False,
                "new_labeled_samples": 0,
                "reason": "no_label_column",
            }

        labeled = data[pd.to_numeric(data[label_col], errors="coerce").notna()].copy()
        if labeled.empty:
            return {
                "fine_tuned": False,
                "new_labeled_samples": 0,
                "reason": "no_labeled_samples",
                "label_col": label_col,
            }

        train_dates = pd.Series(pd.to_datetime(labeled["date"].unique())).sort_values()
        if last_train_date:
            train_dates = train_dates[train_dates > pd.to_datetime(last_train_date)]
        if new_data_start_date is not None:
            train_dates = train_dates[train_dates >= pd.to_datetime(new_data_start_date)]

        if train_dates.empty:
            return {
                "fine_tuned": False,
                "new_labeled_samples": 0,
                "reason": "no_new_labeled_samples",
                "label_col": label_col,
            }

        built = self.build_input(
            raw_data=None,
            feature_data=data,
            prediction_dates=list(train_dates),
            include_labels=True,
            label_col=label_col,
        )

        arrays = []
        dates = []
        for date_value in sorted(built["daily_tensors"]):
            day_values = built["daily_tensors"][date_value]
            if not day_values:
                continue
            arrays.extend(day_values)
            dates.extend([pd.to_datetime(date_value)] * len(day_values))

        if not arrays:
            return {
                "fine_tuned": False,
                "new_labeled_samples": 0,
                "reason": "no_valid_training_windows",
                "label_col": label_col,
            }

        import torch

        stacked = np.stack(arrays).astype(np.float32)
        input_dim = int(built["input_dim"])
        x = stacked[:, :, :input_dim]
        y = stacked[:, -1, input_dim]
        finite_mask = np.isfinite(y)
        x = x[finite_mask]
        y = y[finite_mask]
        dates = [date for date, keep in zip(dates, finite_mask) if bool(keep)]

        if len(y) == 0:
            return {
                "fine_tuned": False,
                "new_labeled_samples": 0,
                "reason": "no_finite_labels",
                "label_col": label_col,
            }

        x_tensor = torch.tensor(x, dtype=torch.float32)
        y_tensor = torch.tensor(y, dtype=torch.float32)
        dataset = torch.utils.data.TensorDataset(x_tensor, y_tensor)
        loader = torch.utils.data.DataLoader(dataset, batch_size=int(batch_size), shuffle=True)

        self.model.train()
        optimizer = torch.optim.AdamW(self.model.parameters(), lr=float(lr), weight_decay=1e-4)
        loss_fn = torch.nn.MSELoss()
        epoch_losses: list[float] = []

        for _ in range(1, int(epochs) + 1):
            total_loss = 0.0
            total_count = 0
            for batch_x, batch_y in loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)
                pred = self.model(torch.nan_to_num(batch_x, nan=0.0, posinf=0.0, neginf=0.0)).reshape(-1)
                pred = torch.nan_to_num(pred, nan=0.0, posinf=20.0, neginf=-20.0).clamp(-20.0, 20.0)
                loss = loss_fn(pred, batch_y)

                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=3.0)
                optimizer.step()

                total_loss += float(loss.item()) * len(batch_x)
                total_count += len(batch_x)
            epoch_losses.append(total_loss / max(total_count, 1))

        self.model.eval()

        saved_path = None
        if save_path:
            saved_path = self.save_model(save_path)
            summary_path = Path(save_path).parent / "summary.json"
            summary_payload = dict(self.summary or {})
            summary_payload["args"] = dict(self.args or summary_payload.get("args") or {})
            summary_payload["fine_tuned_from"] = str(self.checkpoint_path)
            summary_payload["latest_fine_tune_date"] = str(max(dates).date())
            summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self.checkpoint_path = Path(saved_path)

        return {
            "fine_tuned": True,
            "new_labeled_samples": int(len(y)),
            "label_col": label_col,
            "train_start_date": str(min(dates).date()) if dates else "",
            "train_end_date": str(max(dates).date()) if dates else "",
            "epochs": int(epochs),
            "lr": float(lr),
            "loss": float(epoch_losses[-1]) if epoch_losses else None,
            "epoch_losses": epoch_losses,
            "saved_path": str(saved_path) if saved_path else "",
        }

    def save_model(self, path: str | Path) -> Path:
        if not self.loaded:
            self.load()
        import torch

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), out_path)
        return out_path

    def _load_summary(self) -> dict[str, Any]:
        for path in [
            self.checkpoint_path.parent / "summary.json",
            self.checkpoint_path.parent / "metrics.json",
        ]:
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                summary = data.get("summary") if isinstance(data.get("summary"), dict) else data
                summary.setdefault("args", data.get("args", summary.get("args", {})))
                return summary
            except Exception:
                continue

        return {
            "model_name": "DFT_UNET",
            "run_name": "",
            "args": self._default_args(),
            "prediction_sign": 1.0,
        }

    def _load_state_dict(self, torch_module):
        try:
            checkpoint = torch_module.load(self.checkpoint_path, map_location="cpu", weights_only=False)
        except TypeError:
            checkpoint = torch_module.load(self.checkpoint_path, map_location="cpu")

        if isinstance(checkpoint, dict):
            for key in [
                "state_dict",
                "model_state_dict",
                "model",
                "net",
                "network",
                "module",
                "model_state",
            ]:
                value = checkpoint.get(key)
                if isinstance(value, dict) and value:
                    return dict(value)

            tensor_like_count = sum(hasattr(v, "shape") for v in checkpoint.values())
            if tensor_like_count > 0:
                return dict(checkpoint)

        raise RuntimeError("No loadable state_dict found in checkpoint.")

    def _patch_legacy_state_dict_keys(self, state_dict: dict[str, Any]) -> dict[str, Any]:
        patched = dict(state_dict)
        legacy_map = {
            "out.1.trans.weight": "temporal_pool.trans.weight",
            "out.2.weight": "pred_head.weight",
            "out.2.bias": "pred_head.bias",
        }
        for old_key, new_key in legacy_map.items():
            if old_key in patched and new_key not in patched:
                patched[new_key] = patched[old_key]
        return patched

    def _model_kwargs(self) -> dict[str, Any]:
        args = {**self._default_args(), **self.args}
        return {
            "d_feat": int(args["d_feat"]),
            "d_model": int(args["d_model"]),
            "t_nhead": int(args["n_head"]),
            "s_nhead": int(args["s_nhead"]),
            "seq_len": int(args["seq_len"]),
            "S_dropout_rate": float(args["dropout"]),
            "gate_input_start_index": int(args["gate_input_start_index"]),
            "gate_input_end_index": int(args["gate_input_end_index"]),
            "scale_kernels": tuple(args["scale_kernels"]),
            "adaptive_scale": True,
            "router_hidden": int(args["router_hidden"]),
            "router_dropout": float(args["router_dropout"]),
            "router_temperature": float(args["router_temperature"]),
            "router_variant": str(args["router_variant"]),
            "router_kan_basis": int(args["router_kan_basis"]),
            "beta": float(args["beta"]),
            "tab_hidden": int(args["tab_hidden"]),
            "tab_layers": int(args["tab_layers"]),
            "tab_dropout": float(args["tab_dropout"]),
            "unet_levels": int(args["unet_levels"]),
            "unet_dropout": float(args["unet_dropout"]),
            "unet_expansion": int(args["unet_expansion"]),
            "unet_channel_multiplier": int(args["unet_channel_multiplier"]),
            "unet_block_type": str(args["unet_block_type"]),
            "unet_kan_basis": int(args["unet_kan_basis"]),
            "use_unet_pyramid_fusion": bool(args["use_unet_pyramid_fusion"]),
            "unet_pyramid_init_scale": float(args["unet_pyramid_init_scale"]),
            "use_unet_input_residual": bool(args["use_unet_input_residual"]),
            "unet_input_residual_scale": float(args["unet_input_residual_scale"]),
            "use_unet_router_condition": bool(args["use_unet_router_condition"]),
            "unet_router_condition_dropout": float(args["unet_router_condition_dropout"]),
        }

    @staticmethod
    def _default_args() -> dict[str, Any]:
        return {
            "d_feat": 158,
            "d_model": 64,
            "n_head": 4,
            "s_nhead": 2,
            "seq_len": 8,
            "dropout": 0.5,
            "gate_input_start_index": 158,
            "gate_input_end_index": 221,
            "beta": 5.0,
            "scale_kernels": [3, 5, 7],
            "router_hidden": 64,
            "router_dropout": 0.1,
            "router_temperature": 1.0,
            "router_variant": "mlp",
            "router_kan_basis": 6,
            "tab_hidden": 128,
            "tab_layers": 2,
            "tab_dropout": 0.2,
            "unet_levels": 3,
            "unet_dropout": 0.1,
            "unet_expansion": 1,
            "unet_channel_multiplier": 2,
            "unet_block_type": "conv",
            "unet_kan_basis": 6,
            "use_unet_pyramid_fusion": False,
            "unet_pyramid_init_scale": 0.0,
            "use_unet_input_residual": False,
            "unet_input_residual_scale": 0.1,
            "use_unet_router_condition": False,
            "unet_router_condition_dropout": 0.0,
        }

    @staticmethod
    def _input_spec_from_args(args: dict[str, Any]) -> dict[str, Any]:
        merged = {**DFTUNetAdapter._default_args(), **(args or {})}
        return {
            "shape": f"[N, {merged['seq_len']}, {merged['gate_input_end_index']}]",
            "stock_feature_count": int(merged["d_feat"]),
            "market_context_count": int(merged["gate_input_end_index"]) - int(merged["gate_input_start_index"]),
        }

    def _stock_feature_columns(self, feature_data: pd.DataFrame) -> list[str]:
        feature_cols = get_alpha158_feature_cols(feature_data)
        return feature_cols[:158]

    def _market_context_columns(self, feature_data: pd.DataFrame, stock_cols: list[str]) -> list[str]:
        exact = [col for col in MARKET_CONTEXT_COLUMNS if col in feature_data.columns]
        if len(exact) >= 63:
            return exact[:63]

        candidate_prefixes = ("market_", "mkt_", "context_", "gate_")
        prefixed = [
            col for col in feature_data.columns
            if col not in stock_cols
            and pd.api.types.is_numeric_dtype(feature_data[col])
            and str(col).lower().startswith(candidate_prefixes)
        ]
        if len(prefixed) >= 63:
            return prefixed[:63]

        numeric_feature_cols = [
            col for col in get_alpha158_feature_cols(feature_data)
            if col not in stock_cols
        ]
        if len(numeric_feature_cols) >= 63:
            return numeric_feature_cols[:63]
        return prefixed

    @staticmethod
    def _default_label_column(feature_data: pd.DataFrame) -> str | None:
        for col in ["future_5d_score", "future_5d_ret"]:
            if col in feature_data.columns:
                return col
        return None
