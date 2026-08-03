from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from config import KRONOS_MARKET_HISTORY_CACHE_PATH

from kronos_runtime.settings import (
    KRONOS_MODEL_VERSION,
    lab_root,
    market_panel_path,
    model_dir,
    predictor_dir,
    tokenizer_dir,
    validate_kronos_assets,
)


LOOKBACK_WINDOW = 256
KRONOS_FEATURE_COLUMNS = (
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "volume",
    "amount",
)


def _code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _date_text(value: Any) -> str:
    parsed = pd.to_datetime(value, errors="coerce")
    return parsed.strftime("%Y%m%d") if not pd.isna(parsed) else ""


def _time_stamps(dates: pd.Series) -> np.ndarray:
    value = pd.to_datetime(dates.astype(str), format="%Y%m%d")
    return np.column_stack(
        [
            np.zeros(len(value), dtype=np.int64),
            np.zeros(len(value), dtype=np.int64),
            value.dt.weekday.to_numpy(dtype=np.int64),
            value.dt.day.to_numpy(dtype=np.int64),
            value.dt.month.to_numpy(dtype=np.int64),
        ]
    )


@dataclass(frozen=True)
class _InferenceRecord:
    code: str
    name: str
    signal_date: str
    values: np.ndarray
    stamps: np.ndarray
    feature_mean: np.ndarray
    feature_std: np.ndarray
    current_adjusted_close: float
    current_adj_factor: float
    market: dict[str, float]


class KronosMiniInferenceAdapter:
    """Run the trained NeoQuasar/Kronos-mini checkpoint on current CSI300 data.

    The checkpoint contract remains exactly 256 observations by six adjusted
    OHLCVA features. Money-flow sentiment is deliberately fused after this
    adapter so the trained tokenizer and Predictor input shape are unchanged.
    """

    def __init__(self, *, device: str = "cpu", batch_size: int = 32) -> None:
        self.device = torch.device(device)
        self.batch_size = max(1, int(batch_size))
        self.asset_report: dict[str, Any] = {}
        self.coverage_report: dict[str, Any] = {}

    @staticmethod
    def _load_lab_panel() -> pd.DataFrame:
        cache_path = Path(KRONOS_MARKET_HISTORY_CACHE_PATH)
        source_path = market_panel_path()
        if (
            cache_path.exists()
            and source_path.exists()
            and cache_path.stat().st_mtime >= source_path.stat().st_mtime
        ):
            panel = pd.read_csv(
                cache_path,
                dtype={"stock_code": str, "trade_date": str},
                encoding="utf-8-sig",
            )
            panel["code"] = panel["stock_code"].map(_code)
            panel["trade_date"] = panel["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
            return panel
        try:
            panel = pd.read_parquet(source_path).copy()
            compact = (
                panel.sort_values(["stock_code", "trade_date"])
                .groupby("stock_code", sort=False, group_keys=False)
                .tail(320)
                .copy()
            )
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            compact.to_csv(cache_path, index=False, encoding="utf-8-sig")
        except ImportError:
            if not cache_path.exists():
                raise RuntimeError(
                    "容器缺少 parquet 读取器，且 Kronos 紧凑历史缓存尚未生成"
                )
            panel = pd.read_csv(cache_path, dtype={"stock_code": str, "trade_date": str}, encoding="utf-8-sig")
        panel["code"] = panel["stock_code"].map(_code)
        panel["trade_date"] = panel["trade_date"].astype(str).str.replace("-", "", regex=False).str[:8]
        return panel

    @staticmethod
    def _current_rows(raw_data: pd.DataFrame) -> pd.DataFrame:
        required = {"date", "code", "open", "high", "low", "close", "volume", "amount", "adj_factor"}
        missing = sorted(required - set(raw_data.columns))
        if missing:
            raise ValueError(f"Kronos 最新行情缺少字段：{missing}")
        current = raw_data.copy()
        current["code"] = current["code"].map(_code)
        current["trade_date"] = current["date"].map(_date_text)
        numeric = ["open", "high", "low", "close", "volume", "amount", "adj_factor"]
        for column in numeric:
            current[column] = pd.to_numeric(current[column], errors="coerce")
        current = current.dropna(subset=["trade_date", *numeric])
        for column in ("open", "high", "low", "close"):
            current[f"adjusted_{column}"] = current[column] * current["adj_factor"]
        return current

    @staticmethod
    def _market_metrics(frame: pd.DataFrame) -> dict[str, float]:
        current = frame.iloc[-1]
        adjusted_close = pd.to_numeric(frame["adjusted_close"], errors="coerce")
        daily_return = adjusted_close.pct_change(fill_method=None)
        ret_5 = float(adjusted_close.iloc[-1] / adjusted_close.iloc[-6] - 1.0) if len(frame) >= 6 else np.nan
        ret_20 = float(adjusted_close.iloc[-1] / adjusted_close.iloc[-21] - 1.0) if len(frame) >= 21 else np.nan
        vol_20 = float(daily_return.tail(20).std()) if len(frame) >= 21 else np.nan
        rolling_peak = float(adjusted_close.tail(20).max()) if len(frame) else np.nan
        drawdown_20 = float(adjusted_close.iloc[-1] / rolling_peak - 1.0) if rolling_peak > 0 else np.nan
        pct_chg = float(daily_return.iloc[-1] * 100.0) if len(frame) >= 2 else np.nan
        return {
            "open": float(current["open"]),
            "high": float(current["high"]),
            "low": float(current["low"]),
            "close": float(current["close"]),
            "volume": float(current["volume"]),
            "amount": float(current["amount"]),
            "pct_chg": pct_chg,
            "ret_5": ret_5,
            "ret_20": ret_20,
            "vol_20": vol_20,
            "drawdown_20": drawdown_20,
        }

    def _records(
        self,
        *,
        raw_data: pd.DataFrame,
        stock_pool: dict[str, str],
    ) -> tuple[list[_InferenceRecord], str]:
        current = self._current_rows(raw_data)
        if current.empty:
            raise RuntimeError("Kronos 没有可用的最新复权行情")
        signal_date = str(current["trade_date"].max())
        pool = {_code(code): str(name or "") for code, name in stock_pool.items()}
        panel = self._load_lab_panel()
        panel = panel[panel["code"].isin(pool) & panel["trade_date"].le(signal_date)].copy()
        addon_columns = [
            "code", "trade_date", "open", "high", "low", "close", "volume", "amount",
            "adj_factor", "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close",
        ]
        combined = pd.concat([panel, current.loc[:, addon_columns]], ignore_index=True, sort=False)
        combined = combined.sort_values(["code", "trade_date"]).drop_duplicates(
            ["code", "trade_date"], keep="last"
        )

        records: list[_InferenceRecord] = []
        skipped_short: list[str] = []
        skipped_stale: list[str] = []
        for code, frame in combined.groupby("code", sort=True):
            frame = frame.sort_values("trade_date").reset_index(drop=True)
            if str(frame["trade_date"].iloc[-1]) != signal_date:
                skipped_stale.append(code)
                continue
            frame = frame.dropna(subset=list(KRONOS_FEATURE_COLUMNS) + ["adj_factor"])
            if len(frame) < LOOKBACK_WINDOW:
                skipped_short.append(code)
                continue
            history = frame.tail(LOOKBACK_WINDOW).copy()
            values = history.loc[:, KRONOS_FEATURE_COLUMNS].to_numpy(dtype=np.float32, copy=True)
            mean = values.mean(axis=0, dtype=np.float64).astype(np.float32)
            std = np.maximum(values.std(axis=0, dtype=np.float64).astype(np.float32), np.float32(1e-5))
            normalized = np.clip((values - mean) / std, -5.0, 5.0).astype(np.float32)
            records.append(
                _InferenceRecord(
                    code=code,
                    name=pool.get(code, ""),
                    signal_date=signal_date,
                    values=normalized,
                    stamps=_time_stamps(history["trade_date"]),
                    feature_mean=mean,
                    feature_std=std,
                    current_adjusted_close=float(values[-1, 3]),
                    current_adj_factor=float(history["adj_factor"].iloc[-1]),
                    market=self._market_metrics(history),
                )
            )
        self.coverage_report = {
            "signal_date": signal_date,
            "pool_count": len(pool),
            "eligible_count": len(records),
            "coverage": float(len(records) / max(len(pool), 1)),
            "skipped_short_history_count": len(skipped_short),
            "skipped_stale_count": len(skipped_stale),
            "lookback_window": LOOKBACK_WINDOW,
        }
        if len(records) < 15:
            raise RuntimeError(
                f"Kronos 可推理股票不足 15 只：eligible={len(records)}, pool={len(pool)}"
            )
        return records, signal_date

    @staticmethod
    def _import_model_helpers():
        root = lab_root()
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from training.model import load_model_checkpoint, load_pretrained_model

        return load_pretrained_model, load_model_checkpoint

    def predict(
        self,
        *,
        raw_data: pd.DataFrame,
        stock_pool: dict[str, str],
        prediction_date: str,
    ) -> pd.DataFrame:
        self.asset_report = validate_kronos_assets()
        records, signal_date = self._records(raw_data=raw_data, stock_pool=stock_pool)
        load_pretrained_model, load_model_checkpoint = self._import_model_helpers()
        model = load_pretrained_model(
            predictor_id=str(predictor_dir()),
            tokenizer_id=str(tokenizer_dir()),
            gradient_checkpointing=False,
            cache_dir=lab_root() / ".cache" / "huggingface",
        )
        load_model_checkpoint(model, model_dir(), map_location=self.device)
        model.to(self.device).eval()

        rows: list[dict[str, Any]] = []
        with torch.no_grad():
            for start in range(0, len(records), self.batch_size):
                batch = records[start : start + self.batch_size]
                output = model.predict_history(
                    values=torch.from_numpy(np.stack([item.values for item in batch])).to(self.device),
                    stamps=torch.from_numpy(np.stack([item.stamps for item in batch])).to(self.device),
                    feature_mean=torch.from_numpy(np.stack([item.feature_mean for item in batch])).to(self.device),
                    feature_std=torch.from_numpy(np.stack([item.feature_std for item in batch])).to(self.device),
                    current_close=torch.tensor(
                        [item.current_adjusted_close for item in batch], dtype=torch.float32, device=self.device
                    ),
                )
                predicted = output["predicted_values"].float().cpu().numpy()
                returns = output["predicted_return"].float().cpu().numpy()
                ranking_signals = output["ranking_score"].float().cpu().numpy()
                target_confidences = output["confidence"].float().cpu().numpy()
                for index, item in enumerate(batch):
                    divisor = item.current_adj_factor if item.current_adj_factor > 0 else 1.0
                    values = predicted[index] / divisor
                    rows.append(
                        {
                            "date": pd.to_datetime(signal_date).strftime("%Y-%m-%d"),
                            "prediction_date": str(prediction_date),
                            "code": item.code,
                            "name": item.name,
                            **item.market,
                            "pred_open": float(values[0]),
                            "pred_high": float(values[1]),
                            "pred_low": float(values[2]),
                            "pred_close": float(values[3]),
                            "pred_volume": float(predicted[index][4]),
                            "pred_amount": float(predicted[index][5]),
                            "pred_return": float(returns[index]),
                            "target_ranking_signal": float(ranking_signals[index]),
                            "target_confidence": float(target_confidences[index]),
                            "model_version": KRONOS_MODEL_VERSION,
                        }
                    )
        result = pd.DataFrame(rows)
        result["predicted_up_first"] = result["pred_return"].gt(0.0)
        return result.sort_values(
            ["predicted_up_first", "pred_return", "code"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
