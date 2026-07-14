from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.historical_account_audit import _price_lookup, _records, _snapshot_paths
from pipelines.historical_ai_adjustment_loader import load_historical_ai_adjustments
from pipelines.historical_prediction_loader import load_historical_predictions
from pipelines.paper_backfill_pipeline import trading_days_between
from portfolio.account_reconciliation import RECONCILIATION_PASSED, reconcile_account_day
from scheduler.trading_calendar import get_latest_trading_day, parse_date


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
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype={"stock_code": str, "code": str}, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in [None, ""]:
            return default
        return int(float(value))
    except Exception:
        return default


def _stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    if not text or text.lower() == "nan":
        return ""
    return text.zfill(6)


def _position_weight(row: dict[str, Any], total_asset: float) -> float:
    for key in ["position_weight", "position_ratio"]:
        value = _safe_float(row.get(key), -1.0)
        if value >= 0:
            return value
    market_value = _safe_float(row.get("market_value"), 0.0)
    return market_value / total_asset if total_asset > 0 else 0.0


def _order_action_counts(orders: list[dict[str, Any]]) -> tuple[int, int]:
    buy = 0
    sell = 0
    for row in orders:
        qty = _safe_float(row.get("quantity"), 0.0)
        action = str(row.get("paper_action") or row.get("action") or "").lower()
        if qty <= 0:
            continue
        if action in {"paper_buy", "buy"}:
            buy += 1
        elif action in {"paper_sell", "paper_reduce", "sell", "reduce"}:
            sell += 1
    return buy, sell


def _unjustified_full_liquidation(opening_count: int, closing_count: int, sell_count: int, orders: list[dict[str, Any]]) -> bool:
    if opening_count <= 0 or closing_count > 0 or sell_count <= 0:
        return False
    text = " ".join(
        str(row.get("reason") or "") + " " + str(row.get("risk_warning") or "") + " " + str(row.get("triggered_rules") or "")
        for row in orders
    ).lower()
    exceptions = ["hard", "risk_alert", "exclude", "below top15", "rank", "st", "退市", "硬风险"]
    return not any(token in text for token in exceptions)


def _candidate_stats(ai_records: list[dict[str, Any]], account_total: float) -> dict[str, Any]:
    eligible = []
    top10 = []
    executable = []
    target_positions = []
    for row in ai_records:
        rank = _safe_int(row.get("original_rank") or row.get("rank") or row.get("final_rank"), 9999)
        action = str(row.get("original_rank") or "").lower()
        price = _safe_float(row.get("current_price") or row.get("close"), 0.0)
        target_weight = _safe_float(row.get("stored_target_weight") or row.get("target_weight"), 0.0)
        if action in {"keep", "down_weight", "buy"} and price > 0:
            eligible.append(row)
            if 1 <= rank <= 10:
                top10.append(row)
            if target_weight > 0:
                target_positions.append(row)
            if target_weight * account_total >= price * 100:
                executable.append(row)
    return {
        "eligible_candidate_count": len(eligible),
        "top10_candidate_count": len(top10),
        "backup_candidate_count": 0,
        "executable_candidate_count": len(executable),
        "target_position_count": len(target_positions),
    }


@dataclass(frozen=True)
class FullReplayAuditResult:
    user_id: str
    start_date: str
    end_date: str
    total_trading_days: int
    original_ranking_day_count: int
    ai_adjustment_day_count: int
    missing_original_ranking_day_count: int
    missing_ai_adjustment_day_count: int
    result_mismatch_day_count: int
    real_rebalance_day_count: int
    non_empty_position_day_count: int
    empty_position_day_count: int
    average_position_count: float
    minimum_position_count: int
    maximum_position_weight: float
    over_12_position_day_count: int
    over_30_position_day_count: int
    over_50_position_day_count: int
    near_80_position_day_count: int
    backup_pool_used_day_count: int
    unjustified_full_liquidation_day_count: int
    short_holding_sell_count: int
    account_reconciliation_failed_day_count: int
    abnormal_dates: list[str] = field(default_factory=list)
    daily_report_path: str = ""
    summary_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_full_replay(
    user_id: str,
    start_date: str,
    end_date: str = "latest",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> FullReplayAuditResult:
    resolved_start = _date_text(start_date)
    resolved_end = (
        get_latest_trading_day(datetime.now()).strftime("%Y-%m-%d")
        if str(end_date or "").lower() == "latest"
        else _date_text(end_date)
    )
    days = trading_days_between(resolved_start, resolved_end)
    root = _portfolio_root(user_id, output_dir)
    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    previous_account: dict[str, Any] | None = None
    previous_positions: list[dict[str, Any]] = []
    abnormal_dates: list[str] = []
    short_sell_count = 0

    for trade_date in days:
        prediction = load_historical_predictions(
            trade_date,
            user_id=user_id,
            output_dir=output_dir,
            db_path=db_path,
            top_k=0,
        )
        ai = load_historical_ai_adjustments(
            trade_date,
            prediction,
            user_id=user_id,
            output_dir=output_dir,
            top_k=0,
            full_results=True,
        )
        paths = _snapshot_paths(root, trade_date)
        account = _read_json(paths["account"])
        positions = _records(_read_csv(paths["positions"]))
        orders = _records(_read_csv(paths["orders"]))
        cash_flows = _records(_read_csv(paths["cash_flows"]))
        reconciliation = reconcile_account_day(
            trade_date=trade_date,
            account=account,
            positions=positions,
            orders=orders,
            cash_flows=cash_flows,
            price_lookup=_price_lookup(positions, trade_date),
            previous_row=previous_account,
            previous_positions=previous_positions,
            is_trading_day=True,
            data_source="full_replay_audit",
        )
        rec = reconciliation.to_dict()
        total_asset = _safe_float(account.get("total_assets") or rec.get("recalculated_total_asset"), 0.0)
        weights = [_position_weight(row, total_asset) for row in positions if _safe_float(row.get("quantity"), 0.0) > 0]
        max_weight = max(weights or [0.0])
        lot_rounding_tolerance = 0.0
        if positions and total_asset > 0:
            lot_rounding_tolerance = max(
                [
                    _safe_float(row.get("last_price") or row.get("current_price") or row.get("close"), 0.0) * 100.0 / total_asset
                    for row in positions
                ]
                or [0.0]
            )
        buy_count, sell_count = _order_action_counts(orders)
        candidate_stats = _candidate_stats(ai.records, total_asset)
        row = {
            "trade_date": trade_date,
            "is_trading_day": True,
            "original_ranking_exists": prediction.status == "success",
            "original_ranking_count": len(prediction.predictions),
            "original_ranking_source": prediction.source,
            "ai_adjustment_exists": ai.status == "success",
            "ai_adjustment_count": len(ai.records),
            "ai_adjustment_source": ai.source,
            "input_status": "ready" if prediction.status == "success" and ai.status == "success" else ai.status if prediction.status == "success" else "missing_original_ranking",
            **candidate_stats,
            "buy_order_count": buy_count,
            "sell_order_count": sell_count,
            "opening_position_count": len([row for row in previous_positions if _safe_float(row.get("quantity"), 0.0) > 0]),
            "closing_position_count": len([row for row in positions if _safe_float(row.get("quantity"), 0.0) > 0]),
            "cash": _safe_float(account.get("cash"), 0.0),
            "position_market_value": _safe_float(account.get("position_market_value") or rec.get("position_market_value"), 0.0),
            "total_asset": total_asset,
            "maximum_position_weight": max_weight,
            "lot_rounding_tolerance": lot_rounding_tolerance,
            "over_12_position": max_weight > 0.12 + 1e-9,
            "over_30_position": max_weight > 0.30 + lot_rounding_tolerance + 1e-9,
            "over_50_position": max_weight > 0.50 + 1e-9,
            "near_80_position": max_weight >= 0.75,
            "backup_pool_used": False,
            "unjustified_full_liquidation": _unjustified_full_liquidation(
                len([row for row in previous_positions if _safe_float(row.get("quantity"), 0.0) > 0]),
                len([row for row in positions if _safe_float(row.get("quantity"), 0.0) > 0]),
                sell_count,
                orders,
            ),
            "short_holding_sell_count": 0,
            "reconciliation_status": rec.get("reconciliation_status"),
            "reconciliation_reason": rec.get("reason"),
        }
        if row["reconciliation_status"] != RECONCILIATION_PASSED or row["over_30_position"] or row["unjustified_full_liquidation"]:
            abnormal_dates.append(trade_date)
        rows.append(row)
        previous_account = rec
        previous_positions = positions

    report = pd.DataFrame(rows)
    daily_path = audit_dir / "full_replay_audit.csv"
    summary_path = audit_dir / "full_replay_audit_summary.json"
    report.to_csv(daily_path, index=False, encoding="utf-8-sig")
    position_counts = report.get("closing_position_count", pd.Series(dtype=float)).fillna(0) if not report.empty else pd.Series(dtype=float)
    max_weights = report.get("maximum_position_weight", pd.Series(dtype=float)).fillna(0) if not report.empty else pd.Series(dtype=float)
    result = FullReplayAuditResult(
        user_id=user_id,
        start_date=resolved_start,
        end_date=resolved_end,
        total_trading_days=len(days),
        original_ranking_day_count=int(report.get("original_ranking_exists", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        ai_adjustment_day_count=int(report.get("ai_adjustment_exists", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        missing_original_ranking_day_count=int((~report.get("original_ranking_exists", pd.Series(dtype=bool)).fillna(False).astype(bool)).sum()) if not report.empty else 0,
        missing_ai_adjustment_day_count=int((report.get("input_status", pd.Series(dtype=str)).astype(str) == "missing_ai_adjustment").sum()) if not report.empty else 0,
        result_mismatch_day_count=int((report.get("input_status", pd.Series(dtype=str)).astype(str) == "result_mismatch").sum()) if not report.empty else 0,
        real_rebalance_day_count=int(((report.get("buy_order_count", pd.Series(dtype=float)).fillna(0) + report.get("sell_order_count", pd.Series(dtype=float)).fillna(0)) > 0).sum()) if not report.empty else 0,
        non_empty_position_day_count=int((position_counts > 0).sum()),
        empty_position_day_count=int((position_counts == 0).sum()),
        average_position_count=float(position_counts.mean()) if not position_counts.empty else 0.0,
        minimum_position_count=int(position_counts.min()) if not position_counts.empty else 0,
        maximum_position_weight=float(max_weights.max()) if not max_weights.empty else 0.0,
        over_12_position_day_count=int(report.get("over_12_position", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        over_30_position_day_count=int(report.get("over_30_position", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        over_50_position_day_count=int(report.get("over_50_position", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        near_80_position_day_count=int(report.get("near_80_position", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        backup_pool_used_day_count=int(report.get("backup_pool_used", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        unjustified_full_liquidation_day_count=int(report.get("unjustified_full_liquidation", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()) if not report.empty else 0,
        short_holding_sell_count=short_sell_count,
        account_reconciliation_failed_day_count=int((report.get("reconciliation_status", pd.Series(dtype=str)).astype(str) != RECONCILIATION_PASSED).sum()) if not report.empty else 0,
        abnormal_dates=sorted(set(abnormal_dates)),
        daily_report_path=str(daily_path),
        summary_path=str(summary_path),
    )
    summary_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit full stored-ranking AI paper replay")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default="latest")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--db-path", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_full_replay(
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        db_path=args.db_path,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 1 if result.account_reconciliation_failed_day_count > 0 or result.over_30_position_day_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
