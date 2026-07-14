from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from database.repositories import AgentRepository
from scoring.schemas import COMPLIANCE_DISCLAIMER


def _stock_code(value: Any) -> str:
    text = str(value or "").strip()
    return text.split(".")[0].zfill(6) if text else ""


def get_decision_logs(
    user_id: str | None = None,
    trade_date: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        rows = AgentRepository(db_path).list_decision_logs(user_id=user_id)
        if trade_date:
            rows = [row for row in rows if str(row.get("trade_date") or "") == str(trade_date)]
        return {
            "ok": bool(rows),
            "logs": rows,
            "count": len(rows),
            "message": "decision logs loaded" if rows else "no decision logs found",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    except Exception as exc:
        return {
            "ok": False,
            "logs": [],
            "count": 0,
            "message": f"failed to load decision logs: {exc}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }


def get_decision_by_stock(
    user_id: str | None,
    stock_code: str,
    trade_date: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    target = _stock_code(stock_code)
    try:
        rows = AgentRepository(db_path).list_decision_logs(user_id=user_id, stock_code=target)
        if trade_date:
            rows = [row for row in rows if str(row.get("trade_date") or "") == str(trade_date)]
        row = rows[-1] if rows else {}
        return {
            "ok": bool(row),
            "decision": row,
            "message": "decision log loaded" if row else f"no decision log found for {target}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    except Exception as exc:
        return {
            "ok": False,
            "decision": {},
            "message": f"failed to load decision log: {exc}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }


def summarize_decisions(
    user_id: str | None = None,
    trade_date: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    loaded = get_decision_logs(user_id=user_id, trade_date=trade_date, db_path=db_path)
    logs = loaded.get("logs") or []
    adjustment_buckets = Counter()
    for row in logs:
        try:
            value = float(row.get("combined_adjustment") or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            adjustment_buckets["positive"] += 1
        elif value < 0:
            adjustment_buckets["negative"] += 1
        else:
            adjustment_buckets["neutral"] += 1
    effective = Counter(str(row.get("is_effective")) for row in logs if row.get("is_effective") is not None)
    return {
        "ok": loaded.get("ok", False),
        "count": len(logs),
        "adjustment_counts": dict(adjustment_buckets),
        "effectiveness_counts": dict(effective),
        "message": loaded.get("message", ""),
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }
