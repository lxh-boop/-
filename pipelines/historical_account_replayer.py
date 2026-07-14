from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from portfolio.cash_flow import apply_cash_flows_to_account, list_cash_flows, write_cash_flow_history
from portfolio.paper_account import create_default_account, update_account_metrics
from portfolio.performance_metrics import build_nav_record, mark_to_market_positions
from portfolio.portfolio_risk import calculate_portfolio_risk
from portfolio.storage import PortfolioStorage
from portfolio.user_profile import build_user_constraints, default_user_profile, load_user_context
from pipelines.historical_signal_importer import get_historical_price_lookup


@dataclass(frozen=True)
class ReplayDayResult:
    trade_date: str
    status: str
    warnings: list[str] = field(default_factory=list)
    account: Any | None = None
    positions: list[Any] = field(default_factory=list)
    risk_report: Any | None = None
    output_paths: dict[str, str] = field(default_factory=dict)


def replay_hold_day(
    user_id: str,
    trade_date: str,
    initial_cash: float = 100000.0,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    dry_run: bool = False,
    replay_status: str = "success",
    failure_reason: str = "",
) -> ReplayDayResult:
    storage = PortfolioStorage(
        db_path,
        output_dir=Path(output_dir) / "portfolio" / str(user_id),
        use_database=not dry_run,
    )
    account = storage.load_account(f"paper_{user_id}") or create_default_account(user_id, initial_cash=initial_cash)
    positions = storage.load_positions(user_id)
    previous_total_assets = float(account.total_assets or account.initial_cash or 0.0)
    previous_twr = float(account.time_weighted_return or 0.0)
    flows = list_cash_flows(user_id, db_path=db_path, output_dir=output_dir, use_database=not dry_run)
    account, applied, warnings = apply_cash_flows_to_account(
        account,
        flows,
        trade_date,
        db_path=db_path,
        output_dir=output_dir,
        use_database=not dry_run,
        persist_status=not dry_run,
    )
    price_lookup = get_historical_price_lookup([item.stock_code for item in positions], trade_date, output_dir=output_dir)
    if price_lookup:
        positions = mark_to_market_positions(positions, price_lookup, total_assets=previous_total_assets)
    positions_value = sum(float(item.market_value) for item in positions)
    daily_deposit = sum(float(flow.amount or 0.0) for flow in applied if flow.flow_type == "deposit")
    daily_withdrawal = sum(float(flow.amount or 0.0) for flow in applied if flow.flow_type == "withdrawal")
    account = update_account_metrics(
        account,
        positions_value=positions_value,
        previous_total_assets=previous_total_assets,
        daily_deposit=daily_deposit,
        daily_withdrawal=daily_withdrawal,
        daily_fee=0.0,
        cumulative_fee=float(account.cumulative_fee or 0.0),
    )
    nav_history = storage.load_nav_history(user_id)
    previous_nav_peak = max([float(row.get("nav_peak") or row.get("composite_nav") or row.get("nav") or 1.0) for row in nav_history] or [1.0])
    nav_record = build_nav_record(
        account,
        trade_date,
        positions,
        previous_total_assets=previous_total_assets,
        previous_twr=previous_twr,
        previous_nav_peak=previous_nav_peak,
        daily_deposit=daily_deposit,
        daily_withdrawal=daily_withdrawal,
        daily_fee=0.0,
    )
    try:
        _, _, _, constraints = load_user_context(user_id, db_path=db_path)
    except Exception:
        constraints = build_user_constraints(default_user_profile(user_id))
    risk_report = calculate_portfolio_risk(user_id, account, positions, constraints)
    paths: dict[str, str] = {}
    if not dry_run:
        storage.save_account(account)
        storage.save_positions(positions)
        storage.save_nav_record(nav_record)
        storage.save_risk_report(risk_report)
        paths = storage.write_daily_snapshot(
            account=account,
            positions=positions,
            orders=[],
            risk_report=risk_report,
            decisions=[],
            trade_date=trade_date,
        )
        if replay_status != "success":
            for key in ["account_history", "account_history_dated"]:
                account_path = Path(paths.get(key, ""))
                if account_path.exists():
                    try:
                        payload = json.loads(account_path.read_text(encoding="utf-8"))
                        payload.update(
                            {
                                "daily_replay_status": replay_status,
                                "abnormal_snapshot": 1,
                                "abnormal_reason": failure_reason,
                                "strategy_trading_disabled": 1,
                                "positions_carried_forward": 1,
                            }
                        )
                        account_path.write_text(
                            json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
        cash_path = write_cash_flow_history(user_id, trade_date, flows, output_dir=output_dir)
        paths["cash_flows_history"] = str(cash_path)
    return ReplayDayResult(
        trade_date=trade_date,
        status="success",
        warnings=warnings,
        account=account,
        positions=positions,
        risk_report=risk_report,
        output_paths=paths,
    )
