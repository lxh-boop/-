from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from database.repositories import PredictionRepository
from pipelines.replay_normalization import normalize_trade_date_text, trade_date_token
from scoring.schemas import ModelPredictionSignal


@dataclass(frozen=True)
class HistoricalPredictionResult:
    trade_date: str
    status: str
    predictions: list[ModelPredictionSignal] = field(default_factory=list)
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    saved_ranking_path: str = ""


def _date_token(trade_date: str) -> str:
    return trade_date_token(trade_date)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _history_candidates(output_dir: str | Path, trade_date: str) -> list[Path]:
    root = Path(output_dir)
    token = _date_token(trade_date)
    candidates = [
        root / "rankings" / "history" / f"ranking_{token}.csv",
        root / "rankings" / "history" / f"ranking_{trade_date}.csv",
    ]
    candidates.extend(sorted(root.glob(f"ranking_{token}*.csv")))
    candidates.extend(sorted(root.glob(f"ranking_{trade_date}*.csv")))
    return [path for path in candidates if path.name != "ranking_latest.csv"]


def _to_predictions(rows: list[dict[str, Any]], trade_date: str, top_k: int) -> list[ModelPredictionSignal]:
    total = len(rows)
    predictions: list[ModelPredictionSignal] = []
    selected_rows = rows if int(top_k or 0) <= 0 else rows[: max(1, int(top_k))]
    for row in selected_rows:
        data = dict(row)
        data["trade_date"] = trade_date
        data.setdefault("total_count", total)
        predictions.append(ModelPredictionSignal.from_mapping(data))
    return predictions


def _save_user_ranking(rows: list[dict[str, Any]], user_id: str, output_dir: str | Path, trade_date: str) -> Path:
    token = _date_token(trade_date)
    path = Path(output_dir) / "portfolio" / str(user_id) / "history" / "rankings" / f"ranking_{token}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row}) or ["trade_date"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def load_historical_predictions(
    trade_date: str,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    top_k: int = 50,
) -> HistoricalPredictionResult:
    trade_date = normalize_trade_date_text(trade_date)
    warnings: list[str] = []
    for path in _history_candidates(output_dir, trade_date):
        if not path.exists() or path.stat().st_size == 0:
            continue
        rows = _read_csv(path)
        if not rows:
            continue
        saved = _save_user_ranking(rows, user_id, output_dir, trade_date)
        return HistoricalPredictionResult(
            trade_date=trade_date,
            status="success",
            predictions=_to_predictions(rows, trade_date, top_k),
            source=str(path),
            saved_ranking_path=str(saved),
        )

    try:
        rows = PredictionRepository(db_path).list_predictions(trade_date=trade_date)
    except Exception as exc:
        rows = []
        warnings.append(f"failed to read database.model_prediction for {trade_date}: {exc}")
    if rows:
        rows.sort(key=lambda row: int(row.get("pred_rank") or 999999))
        saved = _save_user_ranking(rows, user_id, output_dir, trade_date)
        return HistoricalPredictionResult(
            trade_date=trade_date,
            status="success",
            predictions=_to_predictions(rows, trade_date, top_k),
            source="database.model_prediction",
            warnings=warnings,
            saved_ranking_path=str(saved),
        )

    warnings.append(f"missing historical ranking for {trade_date}; latest ranking was not used.")
    return HistoricalPredictionResult(
        trade_date=trade_date,
        status="missing_prediction",
        warnings=warnings,
    )


def copy_ranking_to_history(source: str | Path, output_dir: str | Path, user_id: str, trade_date: str) -> Path:
    source_path = Path(source)
    target = Path(output_dir) / "portfolio" / str(user_id) / "history" / "rankings" / f"ranking_{_date_token(trade_date)}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target)
    return target
