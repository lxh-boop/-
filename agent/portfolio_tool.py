from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from scoring.schemas import COMPLIANCE_DISCLAIMER


def _portfolio_dir(output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "portfolio"


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return {}, "file not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}, "read json"
    except Exception as exc:
        return {}, f"failed to read json: {exc}"


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], str]:
    if not path.exists():
        return [], "file not found"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file)), "read csv"
    except Exception as exc:
        return [], f"failed to read csv: {exc}"


def _filter_user(rows: list[dict[str, Any]], user_id: str | None) -> list[dict[str, Any]]:
    if not user_id:
        return rows
    return [row for row in rows if str(row.get("user_id") or "") == str(user_id)]


def get_paper_account(user_id: str | None = None, output_dir: str | Path = "outputs") -> dict[str, Any]:
    path = _portfolio_dir(output_dir) / "paper_account.json"
    account, message = _read_json(path)
    if user_id and account and str(account.get("user_id") or "") != str(user_id):
        account = {}
        message = f"paper account for user_id={user_id} not found"
    return {
        "ok": bool(account),
        "account": account,
        "path": str(path),
        "message": message,
        "is_paper_trading": bool(account.get("is_paper_trading", True)),
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_paper_positions(user_id: str | None = None, output_dir: str | Path = "outputs") -> dict[str, Any]:
    path = _portfolio_dir(output_dir) / "paper_positions.csv"
    rows, message = _read_csv(path)
    rows = _filter_user(rows, user_id)
    return {
        "ok": bool(rows),
        "positions": rows,
        "count": len(rows),
        "path": str(path),
        "message": message,
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_paper_orders(user_id: str | None = None, output_dir: str | Path = "outputs") -> dict[str, Any]:
    path = _portfolio_dir(output_dir) / "paper_orders.csv"
    rows, message = _read_csv(path)
    rows = _filter_user(rows, user_id)
    return {
        "ok": bool(rows),
        "orders": rows,
        "count": len(rows),
        "path": str(path),
        "message": message,
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_portfolio_risk(output_dir: str | Path = "outputs") -> dict[str, Any]:
    path = _portfolio_dir(output_dir) / "portfolio_risk_report.json"
    risk, message = _read_json(path)
    return {
        "ok": bool(risk),
        "risk": risk,
        "risk_warnings": list(risk.get("risk_warnings") or risk.get("warnings") or []),
        "path": str(path),
        "message": message,
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def summarize_portfolio(user_id: str | None = None, output_dir: str | Path = "outputs") -> dict[str, Any]:
    account = get_paper_account(user_id=user_id, output_dir=output_dir)
    positions = get_paper_positions(user_id=user_id, output_dir=output_dir)
    orders = get_paper_orders(user_id=user_id, output_dir=output_dir)
    risk = get_portfolio_risk(output_dir=output_dir)
    exposure: Counter[str] = Counter()
    total_position_ratio = 0.0
    for row in positions.get("positions", []):
        industry = str(row.get("industry") or "unknown")
        try:
            ratio = float(row.get("position_ratio") or 0.0)
        except Exception:
            ratio = 0.0
        exposure[industry] += ratio
        total_position_ratio += ratio
    return {
        "ok": bool(account.get("ok") or positions.get("ok") or risk.get("ok")),
        "account": account.get("account") or {},
        "position_count": positions.get("count", 0),
        "order_count": orders.get("count", 0),
        "position_ratio": total_position_ratio,
        "industry_exposure": dict(exposure),
        "risk": risk.get("risk") or {},
        "risk_warnings": risk.get("risk_warnings") or [],
        "is_paper_trading": True,
        "summary": "Paper portfolio summary only; no real trading action is generated.",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }
