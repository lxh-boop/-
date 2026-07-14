from __future__ import annotations

import csv
import json
from dataclasses import fields
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from database.repositories import PortfolioRepository
from portfolio.paper_account import account_from_dict
from portfolio.schemas import PaperAccount, PaperCashFlow, now_text


VALID_FLOW_TYPES = {"deposit", "withdrawal"}
VALID_FLOW_STATUS = {"pending", "applied", "rejected", "cancelled"}
VALID_FLOW_SOURCES = {"app", "cli", "scheduled", "backfill"}


def parse_date_text(value: str | date | datetime) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            token = text[:8] if fmt == "%Y%m%d" else text[:10]
            return datetime.strptime(token, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"invalid effective_date: {value}")


def cash_flow_from_dict(data: dict[str, Any]) -> PaperCashFlow:
    return PaperCashFlow(
        cash_flow_id=str(data.get("cash_flow_id") or ""),
        user_id=str(data.get("user_id") or "default"),
        effective_date=parse_date_text(data.get("effective_date") or datetime.now()),
        flow_type=str(data.get("flow_type") or ""),
        amount=abs(float(data.get("amount") or 0.0)),
        reason=str(data.get("reason") or ""),
        status=str(data.get("status") or "pending"),
        source=str(data.get("source") or "app"),
        run_id=str(data.get("run_id") or ""),
        idempotency_key=str(data.get("idempotency_key") or ""),
        created_at=str(data.get("created_at") or now_text()),
        applied_at=str(data.get("applied_at") or ""),
    )


def make_cash_flow(
    user_id: str,
    flow_type: str,
    amount: float,
    effective_date: str | date | datetime,
    reason: str = "",
    source: str = "app",
    run_id: str = "",
    idempotency_key: str = "",
    status: str = "pending",
    cash_flow_id: str | None = None,
) -> PaperCashFlow:
    flow_type = str(flow_type or "").strip().lower()
    source = str(source or "app").strip().lower()
    status = str(status or "pending").strip().lower()
    amount_value = abs(float(amount or 0.0))
    if flow_type not in VALID_FLOW_TYPES:
        raise ValueError(f"invalid flow_type: {flow_type}")
    if source not in VALID_FLOW_SOURCES:
        raise ValueError(f"invalid source: {source}")
    if status not in VALID_FLOW_STATUS:
        raise ValueError(f"invalid status: {status}")
    if amount_value <= 0:
        raise ValueError("cash flow amount must be greater than 0")
    effective = parse_date_text(effective_date)
    key = idempotency_key or f"{user_id}:{flow_type}:{amount_value:.2f}:{effective}:{reason}"
    return PaperCashFlow(
        cash_flow_id=cash_flow_id or f"cashflow_{uuid4().hex[:12]}",
        user_id=str(user_id or "default"),
        effective_date=effective,
        flow_type=flow_type,
        amount=amount_value,
        reason=str(reason or ""),
        status=status,
        source=source,
        run_id=str(run_id or ""),
        idempotency_key=key,
        created_at=now_text(),
    )


def _csv_path(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "portfolio" / str(user_id) / "paper_cash_flows.csv"


def _history_csv_path(user_id: str, trade_date: str, output_dir: str | Path = "outputs") -> Path:
    token = parse_date_text(trade_date).replace("-", "")
    return Path(output_dir) / "portfolio" / str(user_id) / "history" / "cash_flows" / f"cash_flows_{token}.csv"


def _read_local_flows(user_id: str, output_dir: str | Path = "outputs") -> list[PaperCashFlow]:
    path = _csv_path(user_id, output_dir)
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return [cash_flow_from_dict(row) for row in csv.DictReader(file)]
    except Exception:
        return []


def _write_local_flows(flows: list[PaperCashFlow], user_id: str, output_dir: str | Path = "outputs") -> Path:
    path = _csv_path(user_id, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [field.name for field in fields(PaperCashFlow)]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        for flow in sorted(flows, key=lambda item: (item.effective_date, item.created_at, item.cash_flow_id)):
            writer.writerow(flow.to_dict())
    return path


def list_cash_flows(
    user_id: str,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
) -> list[PaperCashFlow]:
    if use_database:
        try:
            rows = PortfolioRepository(db_path).list_cash_flows(user_id)
            if rows:
                return [cash_flow_from_dict(row) for row in rows]
        except Exception:
            pass
    return _read_local_flows(user_id, output_dir)


def save_cash_flow(
    flow: PaperCashFlow,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
) -> PaperCashFlow:
    if use_database:
        try:
            PortfolioRepository(db_path).insert_cash_flow(flow.to_dict())
        except Exception:
            pass
    flows = [item for item in _read_local_flows(flow.user_id, output_dir) if item.cash_flow_id != flow.cash_flow_id]
    if flow.idempotency_key:
        flows = [item for item in flows if item.idempotency_key != flow.idempotency_key]
    flows.append(flow)
    _write_local_flows(flows, flow.user_id, output_dir)
    return flow


def add_cash_flow(
    user_id: str,
    flow_type: str,
    amount: float,
    effective_date: str | date | datetime,
    reason: str = "",
    source: str = "app",
    run_id: str = "",
    idempotency_key: str = "",
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
) -> PaperCashFlow:
    flow = make_cash_flow(
        user_id=user_id,
        flow_type=flow_type,
        amount=amount,
        effective_date=effective_date,
        reason=reason,
        source=source,
        run_id=run_id,
        idempotency_key=idempotency_key,
    )
    existing = [
        item
        for item in list_cash_flows(user_id, db_path=db_path, output_dir=output_dir, use_database=use_database)
        if item.idempotency_key and item.idempotency_key == flow.idempotency_key
    ]
    return existing[0] if existing else save_cash_flow(flow, db_path=db_path, output_dir=output_dir, use_database=use_database)


def update_cash_flow_status(
    flow: PaperCashFlow,
    status: str,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
    applied_at: str | None = None,
) -> PaperCashFlow:
    status = str(status or "").lower()
    if status not in VALID_FLOW_STATUS:
        raise ValueError(f"invalid cash flow status: {status}")
    updated = PaperCashFlow(
        **{
            **flow.to_dict(),
            "status": status,
            "applied_at": applied_at if applied_at is not None else flow.applied_at,
        }
    )
    if use_database:
        try:
            PortfolioRepository(db_path).update_cash_flow(
                flow.cash_flow_id,
                {"status": updated.status, "applied_at": updated.applied_at},
            )
        except Exception:
            pass
    flows = [item for item in _read_local_flows(flow.user_id, output_dir) if item.cash_flow_id != flow.cash_flow_id]
    flows.append(updated)
    _write_local_flows(flows, flow.user_id, output_dir)
    return updated


def cancel_cash_flow(
    cash_flow_id: str,
    user_id: str | None = None,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
) -> PaperCashFlow:
    flows: list[PaperCashFlow] = []
    if user_id:
        flows = list_cash_flows(user_id, db_path=db_path, output_dir=output_dir, use_database=use_database)
    else:
        root = Path(output_dir) / "portfolio"
        for child in root.iterdir() if root.exists() else []:
            if child.is_dir():
                flows.extend(list_cash_flows(child.name, db_path=db_path, output_dir=output_dir, use_database=use_database))
    flow = next((item for item in flows if item.cash_flow_id == cash_flow_id), None)
    if flow is None:
        raise ValueError(f"cash flow not found: {cash_flow_id}")
    if flow.status != "pending":
        raise ValueError("only pending cash flows can be cancelled")
    return update_cash_flow_status(flow, "cancelled", db_path=db_path, output_dir=output_dir, use_database=use_database)


def summarize_cash_flows(flows: list[PaperCashFlow], as_of_date: str | None = None) -> dict[str, float]:
    cutoff = parse_date_text(as_of_date) if as_of_date else None
    eligible = [
        flow
        for flow in flows
        if flow.status == "applied" and (cutoff is None or flow.effective_date <= cutoff)
    ]
    deposit = sum(flow.amount for flow in eligible if flow.flow_type == "deposit")
    withdrawal = sum(flow.amount for flow in eligible if flow.flow_type == "withdrawal")
    return {"cumulative_deposit": deposit, "cumulative_withdrawal": withdrawal}


def apply_cash_flows_to_account(
    account: PaperAccount | dict[str, Any],
    flows: list[PaperCashFlow],
    trade_date: str,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
    persist_status: bool = True,
) -> tuple[PaperAccount, list[PaperCashFlow], list[str]]:
    account_obj = account if isinstance(account, PaperAccount) else account_from_dict(account)
    warnings: list[str] = []
    applied: list[PaperCashFlow] = []
    cash = float(account_obj.cash)
    cumulative_deposit = float(account_obj.cumulative_deposit or 0.0)
    cumulative_withdrawal = float(account_obj.cumulative_withdrawal or 0.0)
    total_assets = float(account_obj.total_assets or cash)
    cutoff = parse_date_text(trade_date)

    for flow in sorted(flows, key=lambda item: (item.effective_date, item.created_at, item.cash_flow_id)):
        if flow.status != "pending" or flow.effective_date > cutoff:
            continue
        updated_flow = flow
        if flow.flow_type == "deposit":
            cash += flow.amount
            total_assets += flow.amount
            cumulative_deposit += flow.amount
            updated_flow = PaperCashFlow(**{**flow.to_dict(), "status": "applied", "applied_at": now_text()})
            applied.append(updated_flow)
        elif flow.flow_type == "withdrawal":
            if cash >= flow.amount:
                cash -= flow.amount
                total_assets -= flow.amount
                cumulative_withdrawal += flow.amount
                updated_flow = PaperCashFlow(**{**flow.to_dict(), "status": "applied", "applied_at": now_text()})
                applied.append(updated_flow)
            elif total_assets >= flow.amount:
                warnings.append(f"withdrawal {flow.cash_flow_id} is pending because available cash is insufficient.")
                continue
            else:
                warnings.append(f"withdrawal {flow.cash_flow_id} rejected because amount exceeds total assets.")
                updated_flow = PaperCashFlow(**{**flow.to_dict(), "status": "rejected"})
                applied.append(updated_flow)
        if persist_status and updated_flow.status != flow.status:
            update_cash_flow_status(
                updated_flow,
                updated_flow.status,
                db_path=db_path,
                output_dir=output_dir,
                use_database=use_database,
                applied_at=updated_flow.applied_at,
            )

    net_contribution = float(account_obj.initial_cash) + cumulative_deposit - cumulative_withdrawal
    updated_account = PaperAccount(
        account_id=account_obj.account_id,
        user_id=account_obj.user_id,
        initial_cash=account_obj.initial_cash,
        cash=cash,
        total_assets=total_assets,
        daily_return=account_obj.daily_return,
        cumulative_return=account_obj.cumulative_return,
        max_drawdown=account_obj.max_drawdown,
        cumulative_deposit=cumulative_deposit,
        cumulative_withdrawal=cumulative_withdrawal,
        net_contribution=net_contribution,
        absolute_profit=total_assets - net_contribution,
        time_weighted_return=account_obj.time_weighted_return,
        daily_fee=account_obj.daily_fee,
        cumulative_fee=account_obj.cumulative_fee,
        position_market_value=account_obj.position_market_value,
        composite_nav=account_obj.composite_nav,
        nav=account_obj.nav,
        drawdown=account_obj.drawdown,
        is_paper_trading=True,
        updated_at=now_text(),
    )
    return updated_account, applied, warnings


def write_cash_flow_history(
    user_id: str,
    trade_date: str,
    flows: list[PaperCashFlow],
    output_dir: str | Path = "outputs",
) -> Path:
    path = _history_csv_path(user_id, trade_date, output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = [field.name for field in fields(PaperCashFlow)]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=names)
        writer.writeheader()
        for flow in flows:
            writer.writerow(flow.to_dict())
    return path


def reset_cash_flows_from_date(
    user_id: str,
    start_date: str,
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
    use_database: bool = True,
) -> list[PaperCashFlow]:
    cutoff = parse_date_text(start_date)
    reset: list[PaperCashFlow] = []
    for flow in list_cash_flows(user_id, db_path=db_path, output_dir=output_dir, use_database=use_database):
        if flow.effective_date >= cutoff and flow.status == "applied":
            updated = PaperCashFlow(**{**flow.to_dict(), "status": "pending", "applied_at": ""})
            save_cash_flow(updated, db_path=db_path, output_dir=output_dir, use_database=use_database)
            reset.append(updated)
    return reset


def cash_flow_table_rows(flows: list[PaperCashFlow]) -> list[dict[str, Any]]:
    return [flow.to_dict() for flow in sorted(flows, key=lambda item: (item.effective_date, item.created_at))]


def cash_flow_json(flows: list[PaperCashFlow]) -> str:
    return json.dumps(cash_flow_table_rows(flows), ensure_ascii=False, indent=2)
