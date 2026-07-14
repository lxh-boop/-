from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from evaluation.adjustment_metrics import calculate_adjustment_metrics, safe_float


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _stock_code(value: Any) -> str:
    return str(value or "").split(".")[0].zfill(6)


def _has_future_return(record: dict[str, Any]) -> bool:
    return record.get("future_return_5d") not in [None, ""]


def evaluate_ai_adjustment_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a pending or completed evaluation for one AI adjustment row."""

    base = dict(record)
    user_id = str(base.get("user_id") or "default")
    trade_date = str(base.get("trade_date") or base.get("date") or "")
    stock_code = _stock_code(base.get("stock_code") or base.get("code"))
    base["user_id"] = user_id
    base["trade_date"] = trade_date
    base["stock_code"] = stock_code
    base.setdefault("evaluation_id", f"eval_{user_id}_{trade_date}_{stock_code}")
    base.setdefault("created_at", now_text())

    if not _has_future_return(base):
        base.update(
            {
                "evaluation_status": "pending",
                "adjustment_hit": "",
                "avoided_loss": "",
                "missed_gain": "",
                "adjustment_alpha": "",
                "false_down_weight": "",
                "false_keep": "",
                "ai_adjustment_score": "",
            }
        )
        return base

    base["future_return_5d"] = safe_float(base.get("future_return_5d"), 0.0)
    base["future_excess_return_5d"] = safe_float(base.get("future_excess_return_5d"), base["future_return_5d"])
    metrics = calculate_adjustment_metrics(base)
    base.update(metrics)
    base["evaluation_status"] = "evaluated"
    return base


def evaluate_due_adjustments(records: list[dict[str, Any]], as_of_date: str | None = None) -> dict[str, Any]:
    evaluated = [evaluate_ai_adjustment_record(record) for record in records]
    return {
        "as_of_date": as_of_date or "",
        "evaluated_count": sum(1 for row in evaluated if row.get("evaluation_status") == "evaluated"),
        "pending_count": sum(1 for row in evaluated if row.get("evaluation_status") == "pending"),
        "evaluations": evaluated,
    }
