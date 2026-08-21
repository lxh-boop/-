from __future__ import annotations

from collections import Counter
from pathlib import Path

from database.repositories import PortfolioRepository
from scoring.schemas import COMPLIANCE_DISCLAIMER


def get_paper_account(
    user_id: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> dict:
    del output_dir
    user = str(user_id or "default")
    row = PortfolioRepository(db_path).get_paper_account(f"paper_{user}")
    account = dict(row or {})
    return {
        "ok": bool(account),
        "account": account,
        "path": "database/paper_account",
        "message": "read database" if account else f"paper account for user_id={user} not found",
        "is_paper_trading": bool(account.get("is_paper_trading", True)),
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_paper_positions(
    user_id: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> dict:
    del output_dir
    user = str(user_id or "default")
    rows = PortfolioRepository(db_path).list_positions(user)
    return {
        "ok": bool(rows),
        "positions": rows,
        "count": len(rows),
        "path": "database/portfolio_position",
        "message": "read database" if rows else "paper positions not found",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_paper_orders(
    user_id: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> dict:
    del output_dir
    user = str(user_id or "default")
    rows = PortfolioRepository(db_path).list_paper_orders(user_id=user)
    return {
        "ok": bool(rows),
        "orders": rows,
        "count": len(rows),
        "path": "database/paper_order",
        "message": "read database" if rows else "paper orders not found",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def get_portfolio_risk(
    output_dir: str | Path = "outputs",
    user_id: str = "default",
    db_path: str | Path | None = None,
) -> dict:
    del output_dir
    row = PortfolioRepository(db_path).get_latest_risk_snapshot(user_id) or {}
    risk = dict(row.get("report") or {})
    return {
        "ok": bool(risk),
        "risk": risk,
        "risk_warnings": list(risk.get("risk_warnings") or risk.get("warnings") or []),
        "path": "database/portfolio_risk_snapshot",
        "message": "read database" if risk else "portfolio risk snapshot not found",
        "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
    }


def summarize_portfolio(
    user_id: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> dict:
    user = str(user_id or "default")
    account = get_paper_account(user_id=user, output_dir=output_dir, db_path=db_path)
    positions = get_paper_positions(user_id=user, output_dir=output_dir, db_path=db_path)
    orders = get_paper_orders(user_id=user, output_dir=output_dir, db_path=db_path)
    risk = get_portfolio_risk(output_dir=output_dir, user_id=user, db_path=db_path)
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
