from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evaluation.adjustment_metrics import clamp, safe_float


DEFAULT_AI_RELIABILITY_WEIGHT = 0.00
MIN_AI_RELIABILITY_WEIGHT = 0.00
MAX_AI_RELIABILITY_WEIGHT = 1.00
MIN_EVALUATION_COUNT = 20


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _evaluated_rows(records: list[dict[str, Any]], user_id: str, limit: int) -> list[dict[str, Any]]:
    rows = [
        row
        for row in records
        if str(row.get("user_id") or "default") == str(user_id)
        and str(row.get("evaluation_status") or "evaluated") == "evaluated"
        and row.get("ai_adjustment_score") not in [None, ""]
    ]
    rows.sort(key=lambda row: str(row.get("trade_date") or row.get("created_at") or ""))
    return rows[-max(1, int(limit)) :]


def update_ai_reliability_state(
    records: list[dict[str, Any]],
    user_id: str,
    old_state: dict[str, Any] | None = None,
    as_of_date: str = "",
    lookback_count: int = 50,
    min_evaluation_count: int = MIN_EVALUATION_COUNT,
) -> dict[str, Any]:
    old_state = dict(old_state or {})
    old_weight = safe_float(old_state.get("ai_reliability_weight"), DEFAULT_AI_RELIABILITY_WEIGHT)
    rows = _evaluated_rows(records, user_id, lookback_count)

    if len(rows) < int(min_evaluation_count):
        return {
            "user_id": user_id,
            "as_of_date": as_of_date,
            "ai_reliability_weight": 0.0,
            "recent_hit_rate": 0.0,
            "recent_adjustment_alpha": 0.0,
            "recent_avoided_loss": 0.0,
            "recent_missed_gain": 0.0,
            "recent_ai_adjustment_score": 0.0,
            "lookback_count": len(rows),
            "min_evaluation_count": int(min_evaluation_count),
            "status": "cold_start",
            "updated_at": now_text(),
        }

    count = len(rows)
    recent_hit_rate = sum(safe_float(row.get("adjustment_hit")) for row in rows) / count
    recent_adjustment_alpha = sum(safe_float(row.get("adjustment_alpha")) for row in rows) / count
    recent_avoided_loss = sum(safe_float(row.get("avoided_loss")) for row in rows) / count
    recent_missed_gain = sum(safe_float(row.get("missed_gain")) for row in rows) / count
    recent_ai_adjustment_score = sum(safe_float(row.get("ai_adjustment_score")) for row in rows) / count

    updated_weight = old_weight
    if recent_ai_adjustment_score >= 0.60:
        target_weight = min(MAX_AI_RELIABILITY_WEIGHT, old_weight + 0.20)
    elif recent_ai_adjustment_score < 0.40:
        target_weight = 0.0
    else:
        target_weight = old_weight
    target_weight = clamp(target_weight, MIN_AI_RELIABILITY_WEIGHT, MAX_AI_RELIABILITY_WEIGHT)
    new_weight = clamp(0.8 * old_weight + 0.2 * target_weight, MIN_AI_RELIABILITY_WEIGHT, MAX_AI_RELIABILITY_WEIGHT)

    return {
        "user_id": user_id,
        "as_of_date": as_of_date,
        "ai_reliability_weight": new_weight,
        "recent_hit_rate": recent_hit_rate,
        "recent_adjustment_alpha": recent_adjustment_alpha,
        "recent_avoided_loss": recent_avoided_loss,
        "recent_missed_gain": recent_missed_gain,
        "recent_ai_adjustment_score": recent_ai_adjustment_score,
        "lookback_count": count,
        "min_evaluation_count": int(min_evaluation_count),
        "status": "updated",
        "updated_at": now_text(),
    }
