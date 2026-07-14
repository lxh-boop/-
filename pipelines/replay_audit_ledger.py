from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pipelines.daily_result_source_audit import FAILED_CONTINUE, PRICE_INCOMPLETE_CONTINUE, READY
from pipelines.replay_normalization import normalize_stock_code, trade_date_token


STRATEGY_VERSION = "stage5v_fixed_original_top10_recursive_lot_v1"

REMOVED_AI_AUDIT_FIELDS = {
    "final_action",
    "final_score",
    "final_rank",
    "stored_final_action",
    "stored_final_score",
    "risk_penalty",
    "rule_penalty",
    "risk_penalty_score",
    "rule_penalty_score",
    "score_breakdown",
    "forced_action",
    "penalty_score",
    "triggered_rules",
}

REMOVED_AI_AUDIT_TEXT_REPLACEMENTS = {
    "final_action": "position_adjustment",
    "final_score": "original_score",
    "risk_penalty_score": "numeric_adjustment",
    "rule_penalty_score": "execution_constraint",
    "risk_penalty": "numeric_adjustment",
    "rule_penalty": "execution_constraint",
    "forced_action": "execution_constraint",
    "penalty_score": "numeric_adjustment",
    "down_weight": "lower_position_ratio",
    "risk_alert": "risk_note",
    "hold": "hold",
    "exclude": "zero_target_ratio",
    "excluded": "zero_target_ratio",
    "excluding": "zero_target_ratio",
    "keep": "base_signal",
}


def create_replay_run_id(prefix: str = "replay") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return {}


def _as_records(values: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value in values or []:
        data = _as_dict(value)
        if data:
            rows.append(data)
    return rows


def _strip_removed_ai_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dict(row).items() if key not in REMOVED_AI_AUDIT_FIELDS}


def _sanitize_audit_text(value: str) -> str:
    text = str(value)
    for old, new in REMOVED_AI_AUDIT_TEXT_REPLACEMENTS.items():
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])"
        text = re.sub(pattern, new, text, flags=re.IGNORECASE)
    return text


def _sanitize_audit_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _sanitize_audit_value(item)
            for key, item in value.items()
            if key not in REMOVED_AI_AUDIT_FIELDS
        }
    if isinstance(value, list):
        return [_sanitize_audit_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_audit_text(value)
    return value


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


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames or ["empty"])
        writer.writeheader()
        writer.writerows(rows)


def replay_audit_root(audit_root: str | Path = "runtime/replay_audit") -> Path:
    return Path(audit_root)


def list_replay_audit_runs(user_id: str, audit_root: str | Path = "runtime/replay_audit") -> list[str]:
    root = replay_audit_root(audit_root) / str(user_id)
    if not root.exists():
        return []
    runs = []
    for path in root.iterdir():
        if path.is_dir() and (path / "manifest.json").exists():
            runs.append(path.name)
    return sorted(runs, reverse=True)


def list_replay_audit_dates(user_id: str, run_id: str, audit_root: str | Path = "runtime/replay_audit") -> list[str]:
    daily = replay_audit_root(audit_root) / str(user_id) / str(run_id) / "daily"
    if not daily.exists():
        return []
    dates = []
    for path in daily.glob("*.json"):
        token = path.stem[:8]
        if len(token) == 8 and token.isdigit():
            dates.append(f"{token[:4]}-{token[4:6]}-{token[6:8]}")
    return sorted(set(dates), reverse=True)


def load_replay_audit_day(
    user_id: str,
    run_id: str,
    trade_date: str,
    audit_root: str | Path = "runtime/replay_audit",
) -> dict[str, Any]:
    path = replay_audit_root(audit_root) / str(user_id) / str(run_id) / "daily" / f"{trade_date_token(trade_date)}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_replay_audit_markdown(
    user_id: str,
    run_id: str,
    trade_date: str,
    audit_root: str | Path = "runtime/replay_audit",
) -> str:
    path = replay_audit_root(audit_root) / str(user_id) / str(run_id) / "human_readable" / f"{trade_date_token(trade_date)}.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


class ReplayAuditLedger:
    def __init__(
        self,
        user_id: str,
        run_id: str,
        start_date: str,
        end_date: str,
        audit_root: str | Path = "runtime/replay_audit",
        output_dir: str | Path = "outputs",
        strategy_name: str = "hierarchical_top10",
        database_path: str | Path | None = None,
        source_audit_path: str = "",
        source_audit_summary_path: str = "",
    ):
        self.user_id = str(user_id)
        self.run_id = str(run_id)
        self.start_date = str(start_date)
        self.end_date = str(end_date)
        self.audit_root = replay_audit_root(audit_root)
        self.output_dir = Path(output_dir)
        self.root = self.audit_root / self.user_id / self.run_id
        self.strategy_name = strategy_name
        self.database_path = str(database_path or "")
        self.source_audit_path = source_audit_path
        self.source_audit_summary_path = source_audit_summary_path
        self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.daily_rows: list[dict[str, Any]] = []
        self.stock_rows: list[dict[str, Any]] = []
        self.order_rows: list[dict[str, Any]] = []
        self.position_rows: list[dict[str, Any]] = []
        self.account_rows: list[dict[str, Any]] = []
        for name in ["daily", "human_readable", "tables", "failures"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def run_summary_path(self) -> Path:
        return self.root / "run_summary.json"

    def start(self) -> None:
        manifest = self._manifest(status="running", completed_at="")
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        pointer = self.output_dir / "portfolio" / self.user_id / "audit" / "latest_replay_run.json"
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(json.dumps({"run_id": self.run_id, "audit_log_dir": str(self.root)}, ensure_ascii=False, indent=2), encoding="utf-8")

    def _manifest(self, status: str, completed_at: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "created_at": self.created_at,
            "completed_at": completed_at,
            "status": status,
            "strategy_name": self.strategy_name,
            "strategy_version": STRATEGY_VERSION,
            "original_ranking_source": "stored historical ranking",
            "ai_adjustment_source": "stored final recommendations",
            "price_source": "stored ranking/current_price and historical price cache",
            "user_profile_version": "classic_ui_current",
            "fee_config_version": "paper_trading_settings_current",
            "code_commit": _git_commit(),
            "python_version": sys.version.split()[0],
            "database_path": self.database_path,
            "source_file_hashes": {},
            "source_audit_path": self.source_audit_path,
            "source_audit_summary_path": self.source_audit_summary_path,
            "processed_trade_days": len(self.daily_rows),
            "failed_trade_dates": sorted(row["trade_date"] for row in self.daily_rows if row.get("status") != "success"),
            "failure_reasons": {
                row["trade_date"]: row.get("validation_errors", "")
                for row in self.daily_rows
                if row.get("status") != "success"
            },
            "continued_after_failure_count": sum(1 for row in self.daily_rows if row.get("status") != "success"),
        }
        if extra:
            data.update(extra)
        return data

    def finish(self, status: str = "success", extra_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        summary = {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "status": status,
            "processed_trade_days": len(self.daily_rows),
            "failed_trade_dates": sorted(row["trade_date"] for row in self.daily_rows if row.get("status") != "success"),
            "failed_continue_day_count": sum(1 for row in self.daily_rows if row.get("status") == FAILED_CONTINUE),
            "price_incomplete_continue_day_count": sum(1 for row in self.daily_rows if row.get("status") == PRICE_INCOMPLETE_CONTINUE),
            "success_day_count": sum(1 for row in self.daily_rows if row.get("status") == "success"),
            "daily_json_count": len(list((self.root / "daily").glob("*.json"))),
            "daily_markdown_count": len(list((self.root / "human_readable").glob("*.md"))),
            "buy_order_count": sum(int(row.get("buy_count") or 0) for row in self.daily_rows),
            "sell_order_count": sum(int(row.get("sell_count") or 0) for row in self.daily_rows),
            "audit_log_dir": str(self.root),
        }
        if extra_summary:
            summary.update(extra_summary)
        self.run_summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        self.manifest_path.write_text(
            json.dumps(self._manifest(status=status, completed_at=completed_at), ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        _write_csv(self.root / "tables" / "daily_summary.csv", self.daily_rows)
        _write_csv(self.root / "tables" / "stock_decisions.csv", self.stock_rows)
        _write_csv(self.root / "tables" / "orders.csv", self.order_rows)
        _write_csv(self.root / "tables" / "positions.csv", self.position_rows)
        _write_csv(self.root / "tables" / "account_snapshots.csv", self.account_rows)
        return summary

    def _sources(self, prediction: Any, ai_adjustment: Any, source_audit_row: dict[str, Any] | None) -> dict[str, Any]:
        row = source_audit_row or {}
        return {
            "original_ranking_source": getattr(prediction, "source", "") or row.get("original_ranking_source_path", ""),
            "original_ranking_record_id": row.get("original_ranking_source_name", ""),
            "original_ranking_file_path": row.get("original_ranking_source_path", getattr(prediction, "source", "")),
            "original_ranking_file_hash": row.get("original_ranking_source_hash", ""),
            "original_ranking_run_id": row.get("original_ranking_run_id", ""),
            "original_ranking_model_version": row.get("original_ranking_model_version", ""),
            "ai_adjustment_source": getattr(ai_adjustment, "source", "") or row.get("stored_ai_adjustment_source_path", ""),
            "ai_adjustment_record_id": row.get("stored_ai_adjustment_source_name", ""),
            "ai_adjustment_file_path": row.get("stored_ai_adjustment_source_path", getattr(ai_adjustment, "source", "")),
            "ai_adjustment_file_hash": row.get("stored_ai_adjustment_source_hash", ""),
            "ai_adjustment_run_id": row.get("stored_ai_adjustment_run_id", ""),
            "historical_price_source": "stored current_price/close fields",
            "user_config_version": "classic_ui_current",
            "fee_config_version": "paper_trading_settings_current",
            "previous_account_snapshot_id": "",
            "previous_position_snapshot_id": "",
        }

    def _validation(self, source_audit_row: dict[str, Any] | None, prediction: Any, ai_adjustment: Any, status: str, errors: list[str]) -> dict[str, Any]:
        row = source_audit_row or {}
        validation_errors = _parse_json_list(row.get("validation_errors"))
        for item in errors:
            parsed = _parse_json_list(item)
            if parsed:
                validation_errors.extend(parsed)
            elif item:
                validation_errors.append(item)
        return {
            "is_trading_day": True,
            "original_ranking_count": _safe_int(row.get("original_ranking_count"), len(getattr(prediction, "predictions", []) or [])),
            "ai_adjustment_count": _safe_int(row.get("stored_ai_adjustment_count"), len(getattr(ai_adjustment, "records", []) or [])),
            "aligned_stock_count": _safe_int(row.get("aligned_stock_count"), 0),
            "duplicate_rank_count": _safe_int(row.get("duplicate_rank_count"), 0),
            "duplicate_stock_count": _safe_int(row.get("duplicate_stock_count"), 0),
            "missing_ai_stock_codes": _parse_json_list(row.get("missing_ai_stock_codes")),
            "missing_price_stock_codes": _parse_json_list(row.get("missing_price_stock_codes")),
            "date_match": bool(str(row.get("date_match", "True")).lower() in {"true", "1"} if row else True),
            "run_id_match": bool(str(row.get("run_id_match", "True")).lower() in {"true", "1"} if row else True),
            "version_match": bool(str(row.get("version_match", "True")).lower() in {"true", "1"} if row else True),
            "validation_status": status,
            "validation_errors": sorted(set(str(item) for item in validation_errors if item)),
        }

    def _candidate_filtering(self, ai_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for item in ai_records[:30]:
            code = normalize_stock_code(item.get("stock_code") or item.get("code"))
            price = _safe_float(item.get("current_price") or item.get("close") or item.get("price"), 0.0)
            reason_codes = []
            tradable = item.get("is_tradable")
            price_valid = item.get("price_valid")
            if tradable is not None and str(tradable).lower() in {"0", "false", "no"}:
                reason_codes.append("NOT_TRADABLE")
            if price_valid is not None and str(price_valid).lower() in {"0", "false", "no"}:
                reason_codes.append("PRICE_MARKED_INVALID")
            if price <= 0:
                reason_codes.append("INVALID_PRICE")
            if not code:
                reason_codes.append("MISSING_REQUIRED_FIELD")
            rows.append(
                {
                    "stock_code": code,
                    "stock_name": item.get("stock_name") or item.get("name") or "",
                    "original_rank": _safe_int(item.get("original_rank") or item.get("rank") or item.get("pred_rank"), 0),
                    "original_score": _safe_float(item.get("original_score") or item.get("original_pred_score"), 0.0),
                    "news_adjustment": _safe_float(item.get("news_adjustment"), 0.0),
                    "user_adjustment": _safe_float(item.get("user_adjustment"), 0.0),
                    "ai_reliability_weight": _safe_float(item.get("ai_reliability_weight"), 0.0),
                    "effective_news_adjustment": _safe_float(item.get("effective_news_adjustment"), 0.0),
                    "combined_adjustment": _safe_float(item.get("combined_adjustment"), 0.0),
                    "position_adjustment_ratio": _safe_float(
                        item.get("position_adjustment_ratio") or item.get("stored_position_adjustment_ratio"),
                        1.0,
                    ),
                    "price": price,
                    "is_tradable": not (tradable is not None and str(tradable).lower() in {"0", "false", "no"}),
                    "price_valid": price > 0 and not (price_valid is not None and str(price_valid).lower() in {"0", "false", "no"}),
                    "eligible": not reason_codes,
                    "filter_reason_codes": reason_codes,
                }
            )
        return rows

    def _decision_rows(self, plan: Any, orders: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        orders_by_code = {normalize_stock_code(row.get("stock_code")): row for row in orders}
        buys: list[dict[str, Any]] = []
        sells: list[dict[str, Any]] = []
        for decision in _as_records(getattr(plan, "decisions", []) if plan else []):
            code = normalize_stock_code(decision.get("stock_code"))
            order = orders_by_code.get(code, {})
            action = str(order.get("paper_action") or decision.get("action") or "").lower()
            rank = _safe_int(decision.get("original_rank") or decision.get("rank"), 0)
            base_reason = str(decision.get("reason") or "")
            warning = str(decision.get("risk_warning") or "")
            if action in {"paper_buy", "buy"}:
                reason_code = "TOP5_BASE_POSITION" if 1 <= rank <= 5 else "TOP6_TO_TOP10_BASE_POSITION"
                if _safe_float(decision.get("target_weight"), 0.0) > _safe_float(decision.get("current_weight"), 0.0):
                    reason_code = "INCREASE_TO_TARGET_WEIGHT"
                buys.append(
                    {
                        "stock_code": code,
                        "original_rank": rank,
                        "original_score": decision.get("original_score", ""),
                        "news_adjustment": decision.get("news_adjustment", ""),
                        "user_adjustment": decision.get("user_adjustment", ""),
                        "effective_news_adjustment": decision.get("effective_news_adjustment", ""),
                        "combined_adjustment": decision.get("combined_adjustment", ""),
                        "position_adjustment_ratio": decision.get("position_adjustment_ratio", ""),
                        "base_weight": "",
                        "final_target_weight": decision.get("target_weight", 0.0),
                        "current_weight": decision.get("current_weight", 0.0),
                        "target_quantity": decision.get("executable_quantity", 0.0),
                        "buy_quantity": order.get("quantity", 0.0),
                        "execution_price": order.get("executed_price", decision.get("current_price", 0.0)),
                        "fee": order.get("total_fee", 0.0),
                        "buy_reason_code": reason_code,
                        "buy_reason_detail": base_reason,
                    }
                )
            elif action in {"paper_sell", "paper_reduce", "sell", "reduce"}:
                lowered = f"{base_reason} {warning}".lower()
                if "below top15" in lowered or "top15" in lowered:
                    reason_code = "FELL_BELOW_TOP15"
                elif action in {"paper_reduce", "reduce"}:
                    reason_code = "REDUCE_ABOVE_FINAL_TARGET"
                else:
                    reason_code = "REDUCE_ABOVE_FINAL_TARGET"
                qty = _safe_float(order.get("quantity"), 0.0)
                sells.append(
                    {
                        "stock_code": code,
                        "previous_quantity": "",
                        "sell_quantity": qty,
                        "remaining_quantity": "",
                        "previous_original_rank": "",
                        "current_original_rank": rank,
                        "news_adjustment": decision.get("news_adjustment", ""),
                        "user_adjustment": decision.get("user_adjustment", ""),
                        "effective_news_adjustment": decision.get("effective_news_adjustment", ""),
                        "combined_adjustment": decision.get("combined_adjustment", ""),
                        "position_adjustment_ratio": decision.get("position_adjustment_ratio", ""),
                        "target_weight": decision.get("target_weight", 0.0),
                        "current_weight": decision.get("current_weight", 0.0),
                        "sell_reason_code": reason_code,
                        "sell_reason_detail": base_reason or warning,
                        "source_original_ranking_id": "",
                        "source_ai_adjustment_id": decision.get("source_decision_id", ""),
                    }
                )
        return buys, sells

    def write_failure_log(
        self,
        trade_date: str,
        step: str,
        exc: BaseException | None = None,
        message: str = "",
        source: dict[str, Any] | None = None,
        failed_stock_codes: list[str] | None = None,
        previous_success_trade_date: str = "",
    ) -> Path:
        payload = {
            "trade_date": trade_date,
            "failed_step": step,
            "exception_type": type(exc).__name__ if exc else "",
            "exception_message": str(exc) if exc else message,
            "input_source": source or {},
            "read_rows": {},
            "failed_stock_codes": failed_stock_codes or [],
            "previous_success_trade_date": previous_success_trade_date,
            "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else "",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        path = self.root / "failures" / f"{trade_date_token(trade_date)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        return path

    def write_daily(
        self,
        trade_date: str,
        status: str,
        source_audit_row: dict[str, Any] | None = None,
        prediction: Any = None,
        ai_adjustment: Any = None,
        opening_account: Any = None,
        opening_positions: Any = None,
        paper_result: Any = None,
        replay_result: Any = None,
        failure_errors: list[str] | None = None,
        failure_log_path: str = "",
    ) -> dict[str, Path]:
        prediction_records = _as_records(getattr(prediction, "predictions", []) if prediction else [])
        ai_records = [_strip_removed_ai_fields(dict(item)) for item in list(getattr(ai_adjustment, "records", []) or [])]
        if paper_result is not None:
            closing_account = _as_dict(getattr(paper_result, "account", None))
            closing_positions = _as_records(getattr(paper_result, "positions", []) or [])
            orders = [_strip_removed_ai_fields(row) for row in _as_records(getattr(paper_result, "orders", []) or [])]
            plan = getattr(paper_result, "plan", None)
            diagnostics = _as_dict(getattr(plan, "execution_diagnostics", {}) if plan else {})
        else:
            closing_account = _as_dict(getattr(replay_result, "account", None))
            closing_positions = _as_records(getattr(replay_result, "positions", []) if replay_result else [])
            orders = []
            plan = None
            diagnostics = {}
        opening_account_record = _as_dict(opening_account)
        opening_position_records = _as_records(opening_positions)
        buys, sells = self._decision_rows(plan, orders)
        validation = self._validation(source_audit_row, prediction, ai_adjustment, status, failure_errors or [])
        sources = self._sources(prediction, ai_adjustment, source_audit_row)
        candidate_filtering = self._candidate_filtering(ai_records)
        orders = _sanitize_audit_value(orders)
        buys = _sanitize_audit_value(buys)
        sells = _sanitize_audit_value(sells)
        diagnostics = _sanitize_audit_value(diagnostics)
        candidate_filtering = _sanitize_audit_value(candidate_filtering)
        ai_records = _sanitize_audit_value(ai_records)
        replay_status = "success" if status == READY or status == "success" else status
        total_asset = _safe_float(closing_account.get("total_assets"), 0.0)
        cash_value = _safe_float(closing_account.get("cash"), 0.0)
        position_value = _safe_float(closing_account.get("position_market_value"), 0.0)
        if abs(total_asset - cash_value - position_value) <= 0.01:
            account_reconciliation_status = "passed"
        else:
            account_reconciliation_status = closing_account.get("reconciliation_status", "failed")
        position_reconciliation_status = "passed" if replay_status == "success" else "carried_forward"
        record = {
            "trade_date": trade_date,
            "run_id": self.run_id,
            "user_id": self.user_id,
            "status": replay_status,
            "strategy_validation_status": "passed" if replay_status == "success" else "failed_continue",
            "execution_status": replay_status,
            "account_reconciliation_status": account_reconciliation_status,
            "position_reconciliation_status": position_reconciliation_status,
            "continue_policy": {
                "strategy_trading_disabled": replay_status != "success",
                "positions_carried_forward": replay_status != "success",
                "continued_to_next_day": True,
            },
            "sources": sources,
            "validation": validation,
            "opening_account": opening_account_record,
            "opening_positions": opening_position_records,
            "original_ranking": prediction_records[:30],
            "stored_ai_adjustments": [_strip_removed_ai_fields(item) for item in ai_records[:30]],
            "candidate_filtering": candidate_filtering,
            "weight_allocation": diagnostics,
            "lot_execution": {
                "rounds": diagnostics.get("lot_execution_rounds", []),
                "removed_candidates": diagnostics.get("removed_candidates", []),
                "replacement_candidates": diagnostics.get("replacement_candidates", []),
            },
            "sell_decisions": sells,
            "buy_decisions": buys,
            "executed_orders": orders,
            "closing_positions": closing_positions,
            "mark_to_market": {
                "position_market_value": closing_account.get("position_market_value", 0.0),
                "is_price_forward_filled": replay_status == PRICE_INCOMPLETE_CONTINUE,
                "price_source_date": trade_date,
            },
            "closing_account": closing_account,
            "reconciliation": {
                "account_total_assets": closing_account.get("total_assets", 0.0),
                "cash": closing_account.get("cash", 0.0),
                "position_market_value": closing_account.get("position_market_value", 0.0),
                "status": account_reconciliation_status,
                "error": closing_account.get("reconciliation_error", ""),
            },
            "decision_summary": {
                "top10_count": sum(1 for item in candidate_filtering if 1 <= _safe_int(item.get("original_rank"), 0) <= 10),
                "ai_adjusted_count": len([item for item in candidate_filtering if 1 <= _safe_int(item.get("original_rank"), 0) <= 10]),
                "recursive_round_count": len(diagnostics.get("lot_execution_rounds", []) or []),
                "lot_removed_count": len(diagnostics.get("removed_candidates", []) or []),
                "executable_candidate_count": _safe_int(diagnostics.get("executable_candidate_count"), 0),
                "actual_top10_ratio": _safe_float(diagnostics.get("actual_top10_ratio"), 0.0),
                "cash_ratio": _safe_float(closing_account.get("cash"), 0.0) / max(1e-9, _safe_float(closing_account.get("total_assets"), 1.0)),
                "opening_position_count": len(opening_position_records),
                "buy_count": len(buys),
                "sell_count": len(sells),
                "closing_position_count": len(closing_positions),
                "failure_log_path": failure_log_path,
            },
            "reason_summary": self._reason_summary(replay_status, validation, buys, sells, diagnostics),
        }
        record = _sanitize_audit_value(record)
        json_path = self.root / "daily" / f"{trade_date_token(trade_date)}.json"
        md_path = self.root / "human_readable" / f"{trade_date_token(trade_date)}.md"
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
        md_path.write_text(self._markdown(record), encoding="utf-8")

        daily_row = {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "trade_date": trade_date,
            "status": replay_status,
            "original_ranking_count": validation["original_ranking_count"],
            "ai_adjustment_count": validation["ai_adjustment_count"],
            "candidate_count": len(candidate_filtering),
            "target_position_count": _safe_int(diagnostics.get("target_position_count"), 0),
            "top10_count": record["decision_summary"]["top10_count"],
            "ai_adjusted_count": record["decision_summary"]["ai_adjusted_count"],
            "recursive_round_count": record["decision_summary"]["recursive_round_count"],
            "lot_removed_count": record["decision_summary"]["lot_removed_count"],
            "buy_count": len(buys),
            "sell_count": len(sells),
            "opening_position_count": len(opening_position_records),
            "closing_position_count": len(closing_positions),
            "cash": closing_account.get("cash", 0.0),
            "position_market_value": closing_account.get("position_market_value", 0.0),
            "total_asset": closing_account.get("total_assets", 0.0),
            "audit_json_path": str(json_path),
            "audit_md_path": str(md_path),
            "strategy_validation_status": record["strategy_validation_status"],
            "execution_status": record["execution_status"],
            "account_reconciliation_status": record["account_reconciliation_status"],
            "position_reconciliation_status": record["position_reconciliation_status"],
            "validation_errors": ";".join(validation["validation_errors"]),
        }
        self.daily_rows.append(daily_row)
        for item in candidate_filtering:
            self.stock_rows.append(
                {
                    "run_id": self.run_id,
                    "user_id": self.user_id,
                    "trade_date": trade_date,
                    "stock_code": item.get("stock_code", ""),
                    "original_rank": item.get("original_rank", ""),
                    "base_weight": "",
                    "news_adjustment": item.get("news_adjustment", ""),
                    "user_adjustment": item.get("user_adjustment", ""),
                    "effective_news_adjustment": item.get("effective_news_adjustment", ""),
                    "combined_adjustment": item.get("combined_adjustment", ""),
                    "position_adjustment_ratio": item.get("position_adjustment_ratio", ""),
                    "target_weight": "",
                    "target_quantity": "",
                    "executed_quantity": "",
                    "decision": "eligible" if item.get("eligible") else "filtered",
                    "reason_code": ",".join(item.get("filter_reason_codes") or []),
                    "reason_detail": "",
                }
            )
        for item in orders:
            self.order_rows.append({"run_id": self.run_id, "user_id": self.user_id, "trade_date": trade_date, **item})
        for item in closing_positions:
            self.position_rows.append({"run_id": self.run_id, "user_id": self.user_id, "trade_date": trade_date, **item})
        self.account_rows.append({"run_id": self.run_id, "user_id": self.user_id, "trade_date": trade_date, **closing_account})
        return {"json": json_path, "markdown": md_path}

    def _reason_summary(self, status: str, validation: dict[str, Any], buys: list[dict[str, Any]], sells: list[dict[str, Any]], diagnostics: dict[str, Any]) -> list[str]:
        if status != "success":
            return [
                "当日结果校验失败，禁止策略调仓。",
                "继承上一有效交易日收盘持仓，并按可用历史价格盯市。",
                "错误：" + "；".join(validation.get("validation_errors") or []),
            ]
        summary = [
            f"生成买入 {len(buys)} 笔，卖出/减仓 {len(sells)} 笔。",
            "组合使用已保存 AI 修正结果，不重新计算新闻、RAG、LLM 或模型预测。",
        ]
        if diagnostics.get("removed_candidates"):
            summary.append("存在一手不可执行候选，已按固定原始 Top10 逐轮删除并重新分配。")
        if diagnostics.get("over_30_position_count"):
            summary.append("存在超过 30% 上限的候选，需检查一手容差。")
        return summary

    def _markdown(self, record: dict[str, Any]) -> str:
        validation = record.get("validation", {})
        summary = record.get("decision_summary", {})
        account = record.get("closing_account", {})
        lines = [
            f"# {record['trade_date']} 模拟盘决策记录",
            "",
            "## 数据来源",
            f"- 原始排名：{record['sources'].get('original_ranking_file_path', '')}",
            f"- AI 修正：{record['sources'].get('ai_adjustment_file_path', '')}",
            f"- 历史价格：{record['sources'].get('historical_price_source', '')}",
            "",
            "## 数据校验",
            f"- 原始排名 {validation.get('original_ranking_count', 0)} 条",
            f"- AI 修正 {validation.get('ai_adjustment_count', 0)} 条",
            f"- 对齐成功 {validation.get('aligned_stock_count', 0)} 条",
            f"- 校验状态：{record.get('status')}",
            f"- 校验错误：{'；'.join(validation.get('validation_errors') or []) or '无'}",
            "",
            "## 开盘账户",
            f"- 现金：{record.get('opening_account', {}).get('cash', '')}",
            f"- 持仓：{len(record.get('opening_positions') or [])}",
            "",
            "## Top10 主候选",
            ", ".join(item.get("stock_code", "") for item in (record.get("candidate_filtering") or [])[:10]) or "无",
            "",
            "## 权重处理",
            f"- 目标持仓数：{record.get('weight_allocation', {}).get('target_position_count', 0)}",
            f"- 最大单股仓位：{record.get('weight_allocation', {}).get('maximum_position_weight', 0)}",
            f"- 实际主组合仓位：{summary.get('actual_top10_ratio', 0)}",
            "",
            "## 一手约束处理",
            f"- 轮次数：{len(record.get('lot_execution', {}).get('rounds') or [])}",
            f"- 移除候选数：{len(record.get('lot_execution', {}).get('removed_candidates') or [])}",
            f"- 最终可执行股票数：{summary.get('executable_candidate_count', 0)}",
            "",
            "## 买入原因",
            *[f"- {item.get('stock_code')}: {item.get('buy_reason_code')} - {item.get('buy_reason_detail')}" for item in record.get("buy_decisions", [])],
            "",
            "## 卖出原因",
            *[f"- {item.get('stock_code')}: {item.get('sell_reason_code')} - {item.get('sell_reason_detail')}" for item in record.get("sell_decisions", [])],
            "",
            "## 收盘持仓",
            f"- 持仓数量：{summary.get('closing_position_count', 0)}",
            "",
            "## 收盘账户",
            f"- 账户总资产：{account.get('total_assets', '')}",
            f"- 当前现金：{account.get('cash', '')}",
            f"- 持仓市值：{account.get('position_market_value', '')}",
            "",
            "## 对账",
            f"- 账户对账：{record.get('reconciliation', {}).get('status', '')}",
            f"- 策略校验：{record.get('strategy_validation_status', '')}",
            f"- 执行状态：{record.get('execution_status', '')}",
            f"- 持仓对账：{record.get('position_reconciliation_status', '')}",
            "",
            "## 当日决策总结",
            *[f"- {item}" for item in record.get("reason_summary", [])],
            "",
        ]
        return "\n".join(lines)
