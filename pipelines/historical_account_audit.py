from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.historical_signal_importer import get_historical_price_lookup
from portfolio.account_reconciliation import (
    RECONCILIATION_FAILED,
    RECONCILIATION_PASSED,
    is_valid_curve_point,
    reconcile_account_day,
)
from scheduler.trading_calendar import get_latest_trading_day, is_trading_day, parse_date


def _token(value: str) -> str:
    return str(value or "").replace("-", "")[:8]


def _date_text(value: Any) -> str:
    return parse_date(value).strftime("%Y-%m-%d")


def _portfolio_root(user_id: str, output_dir: str | Path = "outputs") -> Path:
    return Path(output_dir) / "portfolio" / str(user_id)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        if path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path, dtype={"stock_code": str, "code": str}, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    return df.to_dict("records")


def _date_range(start_date: str, end_date: str) -> list[str]:
    start = parse_date(start_date)
    end = parse_date(end_date)
    if end < start:
        raise ValueError("end_date cannot be earlier than start_date")
    days = pd.date_range(start=start, end=end, freq="D")
    return [day.strftime("%Y-%m-%d") for day in days]


def _trading_days(start_date: str, end_date: str) -> list[str]:
    return [day for day in _date_range(start_date, end_date) if is_trading_day(day)]


def _snapshot_paths(root: Path, trade_date: str) -> dict[str, Path]:
    token = _token(trade_date)
    return {
        "account": root / "history" / "accounts" / f"account_{token}.json",
        "positions": root / "history" / "positions" / f"positions_{token}.csv",
        "orders": root / "history" / "orders" / f"orders_{token}.csv",
        "cash_flows": root / "history" / "cash_flows" / f"cash_flows_{token}.csv",
    }


def _price_lookup(positions: list[dict[str, Any]], trade_date: str) -> dict[str, float]:
    codes = sorted({str(item.get("stock_code") or item.get("code") or "").split(".")[0].zfill(6) for item in positions if item})
    codes = [code for code in codes if code and code != "000000"]
    if not codes:
        return {}
    try:
        return get_historical_price_lookup(codes, trade_date)
    except Exception:
        return {}


def backup_account_history(user_id: str, output_dir: str | Path = "outputs") -> str:
    root = _portfolio_root(user_id, output_dir)
    if not root.exists():
        return ""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_root = root / "backups" / stamp / "stage5o_before_rebuild"
    backup_root.mkdir(parents=True, exist_ok=True)
    for name in [
        "paper_account.json",
        "paper_account_latest.json",
        "paper_positions.csv",
        "paper_positions_latest.csv",
        "paper_orders.csv",
        "paper_orders_latest.csv",
        "paper_nav_latest.csv",
        "history",
    ]:
        source = root / name
        if not source.exists():
            continue
        target = backup_root / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return str(backup_root)


@dataclass(frozen=True)
class HistoricalAccountAuditResult:
    user_id: str
    start_date: str
    end_date: str
    audit_trading_day_count: int
    passed_count: int
    failed_count: int
    invalid_count: int
    missing_source_count: int
    empty_position_day_count: int
    order_day_count: int
    unexplained_asset_change_day_count: int
    missing_price_day_count: int
    abnormal_dates: list[str] = field(default_factory=list)
    earliest_trusted_date: str = ""
    daily_report_path: str = ""
    summary_path: str = ""
    valid_curve_path: str = ""
    backup_path: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_historical_account(
    user_id: str,
    start_date: str,
    end_date: str = "latest",
    output_dir: str | Path = "outputs",
    backup_before_rebuild: bool = False,
) -> HistoricalAccountAuditResult:
    resolved_start = _date_text(start_date)
    resolved_end = (
        get_latest_trading_day(datetime.now()).strftime("%Y-%m-%d")
        if str(end_date or "").lower() == "latest"
        else _date_text(end_date)
    )
    root = _portfolio_root(user_id, output_dir)
    root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_account_history(user_id, output_dir) if backup_before_rebuild else ""

    rows: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    previous_positions: list[dict[str, Any]] = []
    for trade_date in _trading_days(resolved_start, resolved_end):
        paths = _snapshot_paths(root, trade_date)
        account = _read_json(paths["account"])
        positions = _records(_read_csv(paths["positions"]))
        orders = _records(_read_csv(paths["orders"]))
        cash_flows = _records(_read_csv(paths["cash_flows"]))
        result = reconcile_account_day(
            trade_date=trade_date,
            account=account,
            positions=positions,
            orders=orders,
            cash_flows=cash_flows,
            price_lookup=_price_lookup(positions, trade_date),
            previous_row=previous,
            previous_positions=previous_positions,
            is_trading_day=True,
            data_source="daily_snapshot",
        )
        row = result.to_dict()
        rows.append(row)
        previous = row
        previous_positions = positions

    report = pd.DataFrame(rows)
    daily_path = root / "account_reconciliation_daily.csv"
    valid_path = root / "account_asset_curve_valid.csv"
    if not report.empty:
        report.to_csv(daily_path, index=False, encoding="utf-8-sig")
        valid = report[report.apply(lambda row: is_valid_curve_point(row.to_dict()), axis=1)].copy()
        valid.to_csv(valid_path, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame().to_csv(daily_path, index=False, encoding="utf-8-sig")
        pd.DataFrame().to_csv(valid_path, index=False, encoding="utf-8-sig")

    status = report.get("reconciliation_status", pd.Series(dtype=str)).astype(str) if not report.empty else pd.Series(dtype=str)
    abnormal = report.loc[status != RECONCILIATION_PASSED, "trade_date"].astype(str).tolist() if not report.empty else []
    valid_dates = report.loc[status == RECONCILIATION_PASSED, "trade_date"].astype(str).tolist() if not report.empty else []
    result = HistoricalAccountAuditResult(
        user_id=user_id,
        start_date=resolved_start,
        end_date=resolved_end,
        audit_trading_day_count=len(rows),
        passed_count=int((status == RECONCILIATION_PASSED).sum()) if not status.empty else 0,
        failed_count=int((~status.isin([RECONCILIATION_PASSED, "missing_source", "invalid"])).sum()) if not status.empty else 0,
        invalid_count=int((status == "invalid").sum()) if not status.empty else 0,
        missing_source_count=int((status == "missing_source").sum()) if not status.empty else 0,
        empty_position_day_count=int((report.get("position_count", pd.Series(dtype=float)).fillna(0) == 0).sum()) if not report.empty else 0,
        order_day_count=int(((report.get("buy_order_count", pd.Series(dtype=float)).fillna(0) + report.get("sell_order_count", pd.Series(dtype=float)).fillna(0)) > 0).sum()) if not report.empty else 0,
        unexplained_asset_change_day_count=int(report.get("no_business_event_violation", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        missing_price_day_count=int((report.get("price_missing_count", pd.Series(dtype=float)).fillna(0) > 0).sum()) if not report.empty else 0,
        abnormal_dates=abnormal,
        earliest_trusted_date=valid_dates[0] if valid_dates else "",
        daily_report_path=str(daily_path),
        summary_path=str(root / "account_reconciliation_summary.json"),
        valid_curve_path=str(valid_path),
        backup_path=backup_path,
    )
    Path(result.summary_path).write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit historical AI paper account snapshots")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default="latest")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--backup-before-rebuild", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_historical_account(
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        backup_before_rebuild=args.backup_before_rebuild,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 1 if result.failed_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
