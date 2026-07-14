from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio.schemas import PaperAccount, now_text


def create_default_account(
    user_id: str = "default_user",
    initial_cash: float = 100000.0,
    account_id: str | None = None,
) -> PaperAccount:
    account_id = account_id or f"paper_{user_id}"
    return PaperAccount(
        account_id=account_id,
        user_id=user_id,
        initial_cash=float(initial_cash),
        cash=float(initial_cash),
        total_assets=float(initial_cash),
        net_contribution=float(initial_cash),
        absolute_profit=0.0,
        time_weighted_return=0.0,
        daily_fee=0.0,
        cumulative_fee=0.0,
        position_market_value=0.0,
        composite_nav=1.0,
        nav=1.0,
        drawdown=0.0,
        updated_at=now_text(),
    )


def account_from_dict(data: dict) -> PaperAccount:
    return PaperAccount(
        account_id=str(data.get("account_id") or data.get("id") or "paper_default"),
        user_id=str(data.get("user_id") or "default_user"),
        initial_cash=float(data.get("initial_cash") or 0.0),
        cash=float(data.get("cash") or 0.0),
        total_assets=float(data.get("total_assets") or data.get("cash") or 0.0),
        daily_return=float(data.get("daily_return") or 0.0),
        cumulative_return=float(data.get("cumulative_return") or 0.0),
        max_drawdown=float(data.get("max_drawdown") or 0.0),
        cumulative_deposit=float(data.get("cumulative_deposit") or 0.0),
        cumulative_withdrawal=float(data.get("cumulative_withdrawal") or 0.0),
        net_contribution=float(
            data.get("net_contribution")
            or (
                float(data.get("initial_cash") or 0.0)
                + float(data.get("cumulative_deposit") or 0.0)
                - float(data.get("cumulative_withdrawal") or 0.0)
            )
        ),
        absolute_profit=float(data.get("absolute_profit") or 0.0),
        time_weighted_return=float(data.get("time_weighted_return") or 0.0),
        daily_fee=float(data.get("daily_fee") or 0.0),
        cumulative_fee=float(data.get("cumulative_fee") or 0.0),
        position_market_value=float(data.get("position_market_value") or 0.0),
        composite_nav=float(data.get("composite_nav") or data.get("nav") or 1.0),
        nav=float(data.get("nav") or 1.0),
        drawdown=float(data.get("drawdown") or 0.0),
        is_paper_trading=bool(data.get("is_paper_trading", True)),
        updated_at=str(data.get("updated_at") or now_text()),
    )


def update_account_metrics(
    account: PaperAccount,
    positions_value: float,
    previous_total_assets: float | None = None,
    daily_deposit: float = 0.0,
    daily_withdrawal: float = 0.0,
    daily_fee: float = 0.0,
    cumulative_fee: float | None = None,
) -> PaperAccount:
    total_assets = float(account.cash) + float(positions_value)
    previous = float(previous_total_assets or account.total_assets or account.initial_cash or total_assets)
    external_cash_flow = float(daily_deposit or 0.0) - float(daily_withdrawal or 0.0)
    daily_return = (total_assets - external_cash_flow - previous) / previous if previous > 0 else 0.0
    net_contribution = (
        float(account.initial_cash)
        + float(account.cumulative_deposit or 0.0)
        - float(account.cumulative_withdrawal or 0.0)
    )
    absolute_profit = total_assets - net_contribution
    cumulative_return = absolute_profit / net_contribution if net_contribution > 0 else 0.0
    time_weighted_return = (1.0 + float(account.time_weighted_return or 0.0)) * (1.0 + daily_return) - 1.0
    composite_nav = 1.0 + time_weighted_return
    nav = composite_nav
    drawdown = composite_nav - 1.0
    max_drawdown = min(float(account.max_drawdown), drawdown)
    return PaperAccount(
        account_id=account.account_id,
        user_id=account.user_id,
        initial_cash=account.initial_cash,
        cash=account.cash,
        total_assets=total_assets,
        daily_return=daily_return,
        cumulative_return=cumulative_return,
        max_drawdown=max_drawdown,
        cumulative_deposit=account.cumulative_deposit,
        cumulative_withdrawal=account.cumulative_withdrawal,
        net_contribution=net_contribution,
        absolute_profit=absolute_profit,
        time_weighted_return=time_weighted_return,
        daily_fee=float(daily_fee or 0.0),
        cumulative_fee=float(cumulative_fee if cumulative_fee is not None else account.cumulative_fee or 0.0),
        position_market_value=float(positions_value or 0.0),
        composite_nav=composite_nav,
        nav=nav,
        drawdown=drawdown,
        is_paper_trading=True,
        updated_at=now_text(),
    )


def save_account_json(account: PaperAccount, path: str | Path) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(account.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def load_account_json(path: str | Path) -> PaperAccount:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return account_from_dict(data)


def _portfolio_output_dir(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "portfolio" / str(user_id)


def _read_json(path: Path, default: Any):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(
            path,
            dtype={"code": str, "stock_code": str, "asset_code": str},
            encoding="utf-8-sig",
        )
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _dated_csv_candidates(root: Path, folder: str, prefix: str, trade_date: str | None = None) -> list[Path]:
    history_dir = root / "history" / folder
    if not history_dir.exists():
        return []
    if trade_date:
        token = re.sub(r"\D", "", str(trade_date))[:8]
        return sorted(history_dir.glob(f"{prefix}_{token}*.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    return sorted(history_dir.glob(f"{prefix}_*.csv"), key=lambda path: path.name, reverse=True)


def _date_from_snapshot_name(path: Path, prefix: str) -> str:
    match = re.search(rf"{re.escape(prefix)}_(\d{{8}})", path.stem)
    if not match:
        return ""
    token = match.group(1)
    return f"{token[:4]}-{token[4:6]}-{token[6:8]}"


def _has_real_order(path: Path) -> bool:
    df = _read_csv(path)
    if df.empty:
        return False
    action = df.get("action", pd.Series(dtype=str)).astype(str).str.lower()
    paper_action = df.get("paper_action", pd.Series(dtype=str)).astype(str).str.lower()
    quantity = pd.to_numeric(df.get("quantity", 0), errors="coerce").fillna(0)
    return bool(((action.isin(["buy", "sell"]) | paper_action.isin(["paper_buy", "paper_sell"])) & (quantity > 0)).any())


def _has_rows(df: pd.DataFrame | None) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty


def _records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()
    return pd.DataFrame([dict(record) for record in records])


def _database_snapshot_fallback(user_id: str, output_dir='.', db_path=None) -> dict[str, Any]:
    if not db_path:
        return {}

    try:
        from portfolio.storage import PortfolioStorage
    except Exception:
        return {}

    storage = PortfolioStorage(
        db_path=db_path,
        output_dir=_portfolio_output_dir(user_id, output_dir),
        use_database=True,
    )
    fallback: dict[str, Any] = {}

    try:
        account = storage.load_account(f"paper_{user_id}")
        if account is not None:
            fallback["account"] = account.to_dict()
    except Exception:
        pass

    try:
        rows = storage.repo.list_positions(user_id)
        positions = [
            storage._position_from_record(row).to_dict()
            for row in rows
            if float(row.get("quantity") or 0.0) > 0
        ]
        fallback["positions"] = _records_to_frame(positions)
    except Exception:
        pass

    try:
        rows = storage.repo.list_paper_orders(user_id=user_id)
        orders = [
            storage._order_from_record(row).to_dict()
            for row in rows
            if float(row.get("quantity") or 0.0) > 0
        ]
        fallback["orders"] = _records_to_frame(orders)
    except Exception:
        pass

    try:
        nav_rows = storage.repo.list_nav_history(user_id)
        for row in nav_rows:
            row.setdefault("composite_nav", row.get("nav", 1.0))
            row.setdefault("nav", row.get("composite_nav", 1.0))
        fallback["nav_history"] = _records_to_frame(nav_rows)
    except Exception:
        pass

    try:
        decision_rows = storage.repo.list_paper_decisions(user_id=user_id)
        if decision_rows:
            latest_date = max(str(row.get("trade_date") or "") for row in decision_rows)
            latest_decisions = [
                dict(row)
                for row in decision_rows
                if str(row.get("trade_date") or "") == latest_date
            ]
            fallback["decisions"] = latest_decisions
    except Exception:
        pass

    try:
        settings = storage.repo.get_trading_settings(user_id)
        if settings:
            fallback["trading_settings"] = dict(settings)
    except Exception:
        pass

    return fallback


def _dates_from_frame(df: pd.DataFrame, column: str = "trade_date") -> list[str]:
    if not _has_rows(df) or column not in df.columns:
        return []
    dates = pd.to_datetime(df[column], errors="coerce").dropna()
    return sorted({value.strftime("%Y-%m-%d") for value in dates})


def add_paper_cash_flow(
    user_id,
    flow_type="deposit",
    amount=0.0,
    effective_date=None,
    reason="",
    output_dir=".",
    db_path=None,
    **kwargs,
):
    from portfolio.cash_flow import add_cash_flow, parse_date_text

    effective = parse_date_text(effective_date or pd.Timestamp.today().date())
    flow = add_cash_flow(
        user_id=user_id,
        flow_type=flow_type,
        amount=amount,
        effective_date=effective,
        reason=reason,
        db_path=db_path,
        output_dir=output_dir,
        use_database=bool(db_path),
        **kwargs,
    )
    return flow.to_dict() if hasattr(flow, "to_dict") else flow


def cancel_pending_paper_cash_flow(flow_id, user_id=None, output_dir=".", db_path=None):
    from portfolio.cash_flow import cancel_cash_flow

    flow = cancel_cash_flow(
        flow_id,
        user_id=user_id,
        db_path=db_path,
        output_dir=output_dir,
        use_database=bool(db_path),
    )
    return flow.to_dict() if hasattr(flow, "to_dict") else flow

def list_daily_order_snapshot_dates(user_id, output_dir='.'):
    root = _portfolio_output_dir(user_id, output_dir)
    dates = [
        _date_from_snapshot_name(path, "orders")
        for path in _dated_csv_candidates(root, "orders", "orders")
        if _has_real_order(path)
    ]
    return sorted({date for date in dates if date})

def list_daily_position_snapshot_dates(user_id, output_dir='.'):
    root = _portfolio_output_dir(user_id, output_dir)
    dates = [
        _date_from_snapshot_name(path, "positions")
        for path in _dated_csv_candidates(root, "positions", "positions")
        if path.exists()
    ]
    return sorted({date for date in dates if date})

def load_daily_order_snapshot(user_id, trade_date, output_dir='.'):
    root = _portfolio_output_dir(user_id, output_dir)
    candidates = _dated_csv_candidates(root, "orders", "orders", trade_date)
    for path in candidates:
        if _has_real_order(path):
            return _read_csv(path)
    return pd.DataFrame()

def load_daily_position_snapshot(user_id, trade_date, output_dir='.'):
    root = _portfolio_output_dir(user_id, output_dir)
    token = re.sub(r"\D", "", str(trade_date))[:8]
    exact_candidates = _dated_csv_candidates(root, "positions", "positions", trade_date)
    for path in exact_candidates:
        df = _read_csv(path)
        if not df.empty:
            return df
    prior = []
    for path in _dated_csv_candidates(root, "positions", "positions"):
        date_token = re.sub(r"\D", "", _date_from_snapshot_name(path, "positions"))[:8]
        if date_token and token and date_token <= token:
            prior.append(path)
    for path in sorted(prior, key=lambda item: _date_from_snapshot_name(item, "positions"), reverse=True):
        df = _read_csv(path)
        if not df.empty:
            return df
    return pd.DataFrame()

def load_paper_cash_flows(user_id, output_dir='.', db_path=None):
    from portfolio.cash_flow import list_cash_flows

    flows = list_cash_flows(
        user_id,
        db_path=db_path,
        output_dir=output_dir,
        use_database=bool(db_path),
    )
    return [flow.to_dict() if hasattr(flow, "to_dict") else dict(flow) for flow in flows]

def load_paper_trading_snapshot(user_id, output_dir='.', db_path=None):
    root = _portfolio_output_dir(user_id, output_dir)
    db_fallback = _database_snapshot_fallback(user_id, output_dir=output_dir, db_path=db_path)

    account = _read_json(root / "paper_account_latest.json", None)
    if account is None:
        account = _read_json(root / "paper_account.json", {})
    if not account and db_fallback.get("account"):
        account = db_fallback["account"]

    risk_report = _read_json(root / "portfolio_risk_report_latest.json", None)
    if risk_report is None:
        risk_report = _read_json(root / "portfolio_risk_report.json", {})

    positions = _read_csv(root / "paper_positions_latest.csv")
    if positions.empty:
        positions = _read_csv(root / "paper_positions.csv")
    if positions.empty and _has_rows(db_fallback.get("positions")):
        positions = db_fallback["positions"]

    orders = _read_csv(root / "paper_orders_latest.csv")
    if orders.empty:
        orders = _read_csv(root / "paper_orders.csv")
    if orders.empty and _has_rows(db_fallback.get("orders")):
        orders = db_fallback["orders"]

    nav_history = _read_csv(root / "paper_nav_latest.csv")
    if nav_history.empty and _has_rows(db_fallback.get("nav_history")):
        nav_history = db_fallback["nav_history"]

    paths = [
        root / "paper_account_latest.json",
        root / "paper_account.json",
        root / "paper_positions_latest.csv",
        root / "paper_positions.csv",
        root / "paper_orders_latest.csv",
        root / "paper_orders.csv",
        root / "portfolio_risk_report_latest.json",
        root / "portfolio_risk_report.json",
        root / "ai_paper_decisions_latest.json",
    ]
    decisions = _read_json(root / "ai_paper_decisions_latest.json", [])
    if not decisions and db_fallback.get("decisions"):
        decisions = db_fallback["decisions"]
    diagnostics = _read_json(root / "paper_execution_diagnostics_latest.json", {})
    settings = _read_json(root / "paper_trading_settings.json", {})
    if not settings and db_fallback.get("trading_settings"):
        settings = db_fallback["trading_settings"]

    order_dates = list_daily_order_snapshot_dates(user_id, output_dir)
    if not order_dates:
        order_dates = _dates_from_frame(orders)
    position_dates = list_daily_position_snapshot_dates(user_id, output_dir)
    if not position_dates:
        position_dates = _dates_from_frame(nav_history)

    return {
        "is_available": any(path.exists() for path in paths) or bool(db_fallback),
        "account": account or {},
        "positions": positions,
        "orders": orders,
        "decisions": decisions if isinstance(decisions, list) else [],
        "risk_report": risk_report or {},
        "execution_diagnostics": diagnostics or {},
        "trading_settings": settings or {},
        "nav_history": nav_history,
        "order_snapshot_dates": order_dates,
        "position_snapshot_dates": position_dates,
    }

def load_paper_backfill_status(user_id, output_dir='.'):
    return {"status": "unknown"}

def run_paper_trading_from_latest(user_id, output_dir='.', db_path=None, dry_run=False):
    return {"status": "stub", "message": "Paper trading backend not available"}

def run_ai_paper_backfill(user_id, start_date, end_date, output_dir='.', db_path=None):
    return {"status": "stub", "message": "Paper trading backfill not available"}
