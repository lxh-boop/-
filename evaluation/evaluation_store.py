from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from evaluation.reliability_updater import DEFAULT_AI_RELIABILITY_WEIGHT, MIN_EVALUATION_COUNT


DEFAULT_EVALUATION_DIR = Path("outputs") / "evaluation"
EVALUATION_COLUMNS = [
    "evaluation_id",
    "user_id",
    "trade_date",
    "stock_code",
    "original_pred_score",
    "original_rank",
    "original_target_weight",
    "final_score",
    "target_weight",
    "position_adjustment_ratio",
    "final_action",
    "future_return_1d",
    "future_return_3d",
    "future_return_5d",
    "future_excess_return_5d",
    "future_max_drawdown_5d",
    "adjustment_hit",
    "avoided_loss",
    "missed_gain",
    "adjustment_alpha",
    "false_down_weight",
    "false_keep",
    "ai_adjustment_score",
    "evaluation_status",
    "created_at",
]


def _evaluation_dir(output_dir: str | Path = "outputs") -> Path:
    root = Path(output_dir)
    if root.name == "evaluation":
        return root
    return root / "evaluation"


def evaluation_csv_path(output_dir: str | Path = "outputs") -> Path:
    return _evaluation_dir(output_dir) / "ai_adjustment_evaluation.csv"


def reliability_state_path(output_dir: str | Path = "outputs") -> Path:
    return _evaluation_dir(output_dir) / "ai_reliability_state.json"


def _cold_start_state(user_id: str) -> dict[str, Any]:
    return {
        "user_id": str(user_id),
        "ai_reliability_weight": DEFAULT_AI_RELIABILITY_WEIGHT,
        "recent_hit_rate": 0.0,
        "recent_adjustment_alpha": 0.0,
        "recent_avoided_loss": 0.0,
        "recent_missed_gain": 0.0,
        "recent_ai_adjustment_score": 0.0,
        "lookback_count": 0,
        "min_evaluation_count": MIN_EVALUATION_COUNT,
        "status": "cold_start",
    }


def _normalize_reliability_state(state: dict[str, Any], user_id: str) -> dict[str, Any]:
    normalized = _cold_start_state(user_id)
    normalized.update(state)
    normalized["user_id"] = str(user_id)
    min_count = int(normalized.get("min_evaluation_count") or MIN_EVALUATION_COUNT)
    lookback_count = int(float(normalized.get("lookback_count") or 0))
    status = str(normalized.get("status") or "cold_start")
    if status == "cold_start" or lookback_count < min_count:
        normalized.update(
            {
                "ai_reliability_weight": 0.0,
                "recent_hit_rate": 0.0,
                "recent_adjustment_alpha": 0.0,
                "recent_avoided_loss": 0.0,
                "recent_missed_gain": 0.0,
                "recent_ai_adjustment_score": 0.0,
                "lookback_count": lookback_count,
                "min_evaluation_count": min_count,
                "status": "cold_start",
            }
        )
    return normalized


def load_ai_adjustment_evaluations(output_dir: str | Path = "outputs") -> list[dict[str, Any]]:
    path = evaluation_csv_path(output_dir)
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def append_ai_adjustment_evaluations(
    records: list[dict[str, Any]],
    output_dir: str | Path = "outputs",
) -> Path:
    path = evaluation_csv_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_ai_adjustment_evaluations(output_dir)
    by_id = {row.get("evaluation_id"): row for row in existing if row.get("evaluation_id")}
    for record in records:
        evaluation_id = str(record.get("evaluation_id") or "")
        if evaluation_id:
            by_id[evaluation_id] = record
    rows = list(by_id.values())
    fieldnames = list(EVALUATION_COLUMNS)
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def load_ai_reliability_state(
    user_id: str,
    output_dir: str | Path = "outputs",
) -> dict[str, Any]:
    path = reliability_state_path(output_dir)
    states: dict[str, Any] = {}
    if path.exists() and path.stat().st_size > 0:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            states = loaded if isinstance(loaded, dict) else {}
        except Exception:
            states = {}
    state = dict(states.get(str(user_id)) or {})
    if not state:
        return _cold_start_state(user_id)
    return _normalize_reliability_state(state, user_id)


def save_ai_reliability_state(
    state: dict[str, Any],
    output_dir: str | Path = "outputs",
) -> Path:
    path = reliability_state_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    states: dict[str, Any] = {}
    if path.exists() and path.stat().st_size > 0:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            states = loaded if isinstance(loaded, dict) else {}
        except Exception:
            states = {}
    user_id = str(state.get("user_id") or "default")
    states[user_id] = dict(state)
    path.write_text(json.dumps(states, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
