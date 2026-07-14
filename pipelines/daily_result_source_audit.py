from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from database.repositories import PredictionRepository
from pipelines.fixed_top10_inputs import REQUIRED_AI_COLUMNS, merge_original_ranking_with_ai
from pipelines.replay_normalization import normalize_stock_code, normalize_trade_date_text, trade_date_token
from scheduler.trading_calendar import get_latest_trading_day, is_trading_day, parse_date


READY = "ready"
FAILED_CONTINUE = "failed_continue"
PRICE_INCOMPLETE_CONTINUE = "price_incomplete_continue"

@dataclass(frozen=True)
class DailyResultSourceAuditResult:
    user_id: str
    start_date: str
    end_date: str
    total_trading_days: int
    ready_day_count: int
    failed_continue_day_count: int
    price_incomplete_continue_day_count: int
    original_ranking_complete_day_count: int
    ai_adjustment_complete_day_count: int
    failed_trade_dates: list[str] = field(default_factory=list)
    failure_reasons: dict[str, list[str]] = field(default_factory=dict)
    daily_report_path: str = ""
    summary_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolve_end_date(end_date: str) -> str:
    if str(end_date or "").lower() == "latest":
        return get_latest_trading_day(datetime.now()).strftime("%Y-%m-%d")
    return normalize_trade_date_text(end_date)


def _trading_days(start_date: str, end_date: str) -> list[str]:
    start = parse_date(start_date)
    end = parse_date(end_date)
    days: list[str] = []
    current = start
    while current <= end:
        if is_trading_day(current):
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return days


def _ranking_candidates(output_dir: str | Path, trade_date: str) -> list[Path]:
    root = Path(output_dir)
    token = trade_date_token(trade_date)
    candidates = [
        root / "rankings" / "history" / f"ranking_{token}.csv",
        root / "rankings" / "history" / f"ranking_{trade_date}.csv",
    ]
    candidates.extend(sorted(root.glob(f"ranking_{token}*.csv")))
    candidates.extend(sorted(root.glob(f"ranking_{trade_date}*.csv")))
    return [path for path in candidates if path.name != "ranking_latest.csv"]


def _ai_candidates(output_dir: str | Path, user_id: str, trade_date: str) -> list[Path]:
    root = Path(output_dir)
    token = trade_date_token(trade_date)
    candidates = [
        root / "users" / str(user_id) / "recommendations" / f"final_recommendations_{token}.csv",
        root / "users" / str(user_id) / "recommendations" / f"final_recommendations_{trade_date}.csv",
        root / "recommendations" / "history" / f"final_recommendations_{token}.csv",
        root / "recommendations" / f"final_recommendations_{token}.csv",
    ]
    return [path for path in candidates if path.name != "final_recommendations_latest.csv"]


def _file_hash(path: Path | None) -> str:
    if not path or not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    if not path.exists():
        return [], []
    if path.stat().st_size == 0:
        return [], []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            return rows, list(reader.fieldnames or [])
    except (csv.Error, OSError, UnicodeDecodeError):
        return [], []


def _first_existing_csv(candidates: list[Path]) -> tuple[Path | None, list[dict[str, Any]], list[str], bool]:
    saw_existing = False
    for path in candidates:
        if not path.exists():
            continue
        saw_existing = True
        rows, columns = _read_csv(path)
        return path, rows, columns, bool(rows)
    return None, [], [], saw_existing


def _db_prediction_rows(db_path: str | Path | None, trade_date: str) -> list[dict[str, Any]]:
    try:
        return PredictionRepository(db_path).list_predictions(trade_date=trade_date)
    except Exception:
        return []


def _row_date(row: dict[str, Any], fallback: str) -> str:
    value = row.get("trade_date") or row.get("date") or row.get("signal_date") or fallback
    try:
        return normalize_trade_date_text(value)
    except Exception:
        return ""


def _rank_value(row: dict[str, Any], fallback: int = 999999) -> int:
    for key in ["original_rank", "original_pred_rank", "pred_rank", "rank", "final_rank"]:
        try:
            value = row.get(key)
            if value not in [None, ""]:
                return int(float(value))
        except Exception:
            continue
    return fallback


def _score_value(row: dict[str, Any]) -> float:
    for key in ["original_score", "original_pred_score", "pred_score", "score", "final_score"]:
        try:
            value = row.get(key)
            if value not in [None, ""]:
                return float(value)
        except Exception:
            continue
    return 0.0


def _price_value(*rows: dict[str, Any]) -> float:
    for row in rows:
        for key in ["current_price", "close", "price", "executed_price", "last_price"]:
            try:
                value = row.get(key)
                if value not in [None, ""]:
                    price = float(value)
                    if price > 0:
                        return price
            except Exception:
                continue
    return 0.0


def _run_id(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        for key in ["run_id", "job_id", "batch_id"]:
            if row.get(key):
                return str(row.get(key))
    return ""


def _model_version(rows: list[dict[str, Any]]) -> str:
    for row in rows:
        for key in ["model_version", "model_name", "model_id"]:
            if row.get(key):
                return str(row.get(key))
    return ""


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for value in values:
        if not value:
            continue
        if value in seen:
            dup.add(value)
        seen.add(value)
    return sorted(dup)


def audit_one_trade_date(
    user_id: str,
    trade_date: str,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    minimum_required_count: int = 10,
    full_ai_results: bool = False,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    ranking_path, ranking_rows, ranking_columns, ranking_has_rows = _first_existing_csv(_ranking_candidates(output_dir, trade_date))
    ranking_source = str(ranking_path) if ranking_path else ""
    if not ranking_rows:
        db_rows = _db_prediction_rows(db_path, trade_date)
        if db_rows:
            ranking_rows = db_rows
            ranking_columns = sorted({key for row in db_rows for key in row})
            ranking_source = "database.model_prediction"
            ranking_has_rows = True
    if not ranking_source:
        errors.append("missing_original_ranking")
    elif not ranking_has_rows:
        errors.append("empty_original_ranking")

    ai_path, ai_rows, ai_columns, ai_has_rows = _first_existing_csv(_ai_candidates(output_dir, user_id, trade_date))
    ai_source = str(ai_path) if ai_path else ""
    if not ai_source:
        errors.append("missing_ai_adjustment")
    elif not ai_has_rows:
        errors.append("empty_ai_adjustment")

    ranking_codes = [normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("ts_code")) for row in ranking_rows]
    ai_codes = [normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("ts_code")) for row in ai_rows]
    invalid_ranking_codes = [str(row.get("stock_code") or row.get("code") or "") for row, code in zip(ranking_rows, ranking_codes) if not code]
    invalid_ai_codes = [str(row.get("stock_code") or row.get("code") or "") for row, code in zip(ai_rows, ai_codes) if not code]
    duplicate_stock_codes = sorted(set(_duplicate_values(ranking_codes) + _duplicate_values(ai_codes)))
    duplicate_ranks = _duplicate_values([str(_rank_value(row, 0)) for row in ranking_rows if _rank_value(row, 0) > 0])

    required_top_count = max(1, min(10, int(minimum_required_count or 10)))
    if len(ranking_rows) and len(ranking_rows) < required_top_count:
        errors.append(f"original_ranking_count_lt_{required_top_count}")
    if invalid_ranking_codes:
        errors.append("invalid_original_stock_code")
    if invalid_ai_codes:
        errors.append("invalid_ai_stock_code")
    if duplicate_stock_codes:
        errors.append("duplicate_stock_code")
    if duplicate_ranks:
        errors.append("duplicate_original_rank")

    ranking_date_match = all(_row_date(row, trade_date) == trade_date for row in ranking_rows) if ranking_rows else False
    ai_date_match = all(_row_date(row, trade_date) == trade_date for row in ai_rows) if ai_rows else False
    if ranking_rows and not ranking_date_match:
        errors.append("original_trade_date_mismatch")
    if ai_rows and not ai_date_match:
        errors.append("ai_trade_date_mismatch")

    missing_ai_columns = sorted(REQUIRED_AI_COLUMNS - set(ai_columns)) if ai_rows else []
    if missing_ai_columns:
        errors.append("missing_ai_required_columns")

    merged = merge_original_ranking_with_ai(
        ranking_rows,
        ai_rows,
        trade_date=trade_date,
        top_n=required_top_count,
        required_ai_columns=REQUIRED_AI_COLUMNS,
    )
    top_codes = [str(row.get("stock_code") or "") for row in merged.original_top10]
    missing_ai_codes = list(merged.missing_ai_stock_codes)
    aligned_codes = [code for code in top_codes if code and code not in set(missing_ai_codes)]
    if missing_ai_codes:
        errors.append("missing_ai_for_original_top10")
    if merged.date_mismatch_codes:
        errors.append("ai_trade_date_mismatch")

    rank_mismatches: list[str] = []
    score_mismatches: list[str] = []
    missing_price_codes: list[str] = []
    merged_by_code = {str(row.get("stock_code") or ""): row for row in merged.original_top10}
    for code in aligned_codes:
        row = merged_by_code.get(code, {})
        if _price_value(row) <= 0:
            missing_price_codes.append(code)

    price_coverage = max(0, len(aligned_codes) - len(missing_price_codes))
    status = READY
    if errors:
        status = FAILED_CONTINUE
    elif missing_price_codes:
        status = PRICE_INCOMPLETE_CONTINUE
        warnings.append("price_incomplete")

    return {
        "trade_date": trade_date,
        "is_trading_day": True,
        "original_ranking_source_path": ranking_source,
        "original_ranking_source_name": Path(ranking_source).name if ranking_source and ranking_source != "database.model_prediction" else ranking_source,
        "original_ranking_source_hash": _file_hash(ranking_path),
        "original_ranking_run_id": _run_id(ranking_rows),
        "original_ranking_model_version": _model_version(ranking_rows),
        "original_ranking_count": len(ranking_rows),
        "stored_ai_adjustment_source_path": ai_source,
        "stored_ai_adjustment_source_name": Path(ai_source).name if ai_source else "",
        "stored_ai_adjustment_source_hash": _file_hash(ai_path),
        "stored_ai_adjustment_run_id": _run_id(ai_rows),
        "stored_ai_adjustment_count": len(ai_rows),
        "aligned_stock_count": len(aligned_codes),
        "missing_stock_count": len(missing_ai_codes),
        "missing_ai_stock_codes": json.dumps(missing_ai_codes, ensure_ascii=False),
        "original_top10_stock_codes": json.dumps(top_codes, ensure_ascii=False),
        "original_top10_ai_merge_ready": bool(not missing_ai_codes and not merged.missing_required_ai_columns and not merged.date_mismatch_codes),
        "historical_price_coverage_count": price_coverage,
        "missing_price_stock_codes": json.dumps(missing_price_codes, ensure_ascii=False),
        "invalid_original_codes": json.dumps(invalid_ranking_codes, ensure_ascii=False),
        "invalid_ai_codes": json.dumps(invalid_ai_codes, ensure_ascii=False),
        "duplicate_stock_codes": json.dumps(duplicate_stock_codes, ensure_ascii=False),
        "duplicate_rank_count": len(duplicate_ranks),
        "duplicate_stock_count": len(duplicate_stock_codes),
        "rank_mismatch_codes": json.dumps(rank_mismatches, ensure_ascii=False),
        "score_mismatch_codes": json.dumps(score_mismatches, ensure_ascii=False),
        "date_match": bool(ranking_date_match and ai_date_match),
        "run_id_match": True if not (_run_id(ranking_rows) and _run_id(ai_rows)) else _run_id(ranking_rows) == _run_id(ai_rows),
        "version_match": True,
        "final_validation_status": status,
        "validation_errors": json.dumps(sorted(set(errors)), ensure_ascii=False),
        "validation_warnings": json.dumps(sorted(set(warnings)), ensure_ascii=False),
    }


def audit_daily_result_sources(
    user_id: str,
    start_date: str,
    end_date: str = "latest",
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
    minimum_required_count: int = 10,
    full_ai_results: bool = False,
) -> DailyResultSourceAuditResult:
    resolved_start = normalize_trade_date_text(start_date)
    resolved_end = _resolve_end_date(end_date)
    days = _trading_days(resolved_start, resolved_end)
    audit_dir = Path(output_dir) / "portfolio" / str(user_id) / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        audit_one_trade_date(
            user_id=user_id,
            trade_date=day,
            output_dir=output_dir,
            db_path=db_path,
            minimum_required_count=minimum_required_count,
            full_ai_results=full_ai_results,
        )
        for day in days
    ]
    report = pd.DataFrame(rows)
    daily_path = audit_dir / "daily_result_source_audit.csv"
    summary_path = audit_dir / "daily_result_source_audit_summary.json"
    report.to_csv(daily_path, index=False, encoding="utf-8-sig")

    status = report.get("final_validation_status", pd.Series(dtype=str)).astype(str) if not report.empty else pd.Series(dtype=str)
    failures = report[status == FAILED_CONTINUE] if not report.empty else pd.DataFrame()
    failure_reasons = {}
    for _, row in failures.iterrows():
        try:
            reasons = json.loads(str(row.get("validation_errors") or "[]"))
        except Exception:
            reasons = [str(row.get("validation_errors") or "unknown")]
        failure_reasons[str(row.get("trade_date"))] = reasons
    result = DailyResultSourceAuditResult(
        user_id=user_id,
        start_date=resolved_start,
        end_date=resolved_end,
        total_trading_days=len(days),
        ready_day_count=int((status == READY).sum()) if not status.empty else 0,
        failed_continue_day_count=int((status == FAILED_CONTINUE).sum()) if not status.empty else 0,
        price_incomplete_continue_day_count=int((status == PRICE_INCOMPLETE_CONTINUE).sum()) if not status.empty else 0,
        original_ranking_complete_day_count=int((report.get("original_ranking_count", pd.Series(dtype=float)).fillna(0).astype(float) >= max(1, min(10, int(minimum_required_count or 10)))).sum()) if not report.empty else 0,
        ai_adjustment_complete_day_count=int((report.get("original_top10_ai_merge_ready", pd.Series(dtype=bool)).astype(str).str.lower().isin(["true", "1"])).sum()) if not report.empty else 0,
        failed_trade_dates=sorted(str(item) for item in failures.get("trade_date", pd.Series(dtype=str)).tolist()),
        failure_reasons=failure_reasons,
        daily_report_path=str(daily_path),
        summary_path=str(summary_path),
    )
    summary_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_daily_source_audit_rows(path: str | Path) -> dict[str, dict[str, Any]]:
    source = Path(path)
    if not source.exists() or source.stat().st_size == 0:
        return {}
    df = pd.read_csv(source, dtype=str, encoding="utf-8-sig").fillna("")
    return {str(row["trade_date"]): dict(row) for _, row in df.iterrows() if row.get("trade_date")}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit stored daily ranking and AI adjustment sources")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default="latest")
    parser.add_argument("--output-dir", default="outputs")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--minimum-required-count", type=int, default=10)
    parser.add_argument("--full-ai-results", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_daily_result_sources(
        user_id=args.user_id,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=args.output_dir,
        db_path=args.db_path,
        minimum_required_count=args.minimum_required_count,
        full_ai_results=args.full_ai_results,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
