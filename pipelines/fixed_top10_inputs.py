from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from pipelines.replay_normalization import normalize_stock_code, normalize_trade_date_text


REQUIRED_AI_COLUMNS = {
    "trade_date",
    "stock_code",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 9999) -> int:
    try:
        if value in [None, ""]:
            return default
        return int(float(value))
    except Exception:
        return default


def _row_date(row: dict[str, Any], fallback: str) -> str:
    value = row.get("trade_date") or row.get("date") or row.get("signal_date") or fallback
    try:
        return normalize_trade_date_text(value)
    except Exception:
        return ""


def original_rank(row: dict[str, Any], fallback: int = 9999) -> int:
    return _safe_int(
        row.get("original_rank")
        or row.get("original_pred_rank")
        or row.get("pred_rank")
        or row.get("rank")
        or row.get("final_rank"),
        fallback,
    )


def original_score(row: dict[str, Any]) -> float:
    return _safe_float(
        row.get("original_score")
        or row.get("original_pred_score")
        or row.get("pred_score")
        or row.get("score")
        or row.get("final_score"),
        0.0,
    )


def final_score(row: dict[str, Any]) -> float:
    return _safe_float(row.get("final_score") or row.get("score") or row.get("pred_score"), 0.0)


def current_price(*rows: dict[str, Any]) -> float:
    for row in rows:
        for key in ["current_price", "close", "price", "executed_price", "last_price"]:
            price = _safe_float(row.get(key), 0.0)
            if price > 0:
                return price
    return 0.0


def canonical_original_rows(rows: list[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    canonical: list[dict[str, Any]] = []
    for index, row in enumerate(rows or [], start=1):
        code = normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("ts_code"))
        if not code:
            continue
        data = dict(row)
        rank = original_rank(data, index)
        score = original_score(data)
        price = current_price(data)
        data.update(
            {
                "trade_date": trade_date,
                "stock_code": code,
                "code": code,
                "stock_name": data.get("stock_name") or data.get("name") or "",
                "original_rank": rank,
                "original_score": score,
                "original_pred_rank": rank,
                "original_pred_score": score,
                "rank": rank,
                "current_price": price,
                "close": price,
            }
        )
        canonical.append(data)
    return sorted(canonical, key=lambda item: (original_rank(item), -original_score(item), str(item.get("stock_code") or "")))


def select_fixed_original_top10(rows: list[dict[str, Any]], top_n: int = 10) -> list[dict[str, Any]]:
    return sorted(
        [dict(row) for row in rows or []],
        key=lambda item: (original_rank(item), -original_score(item), str(item.get("stock_code") or "")),
    )[: max(1, int(top_n or 10))]


@dataclass(frozen=True)
class FixedTop10MergeResult:
    trade_date: str
    original_rows: list[dict[str, Any]] = field(default_factory=list)
    ai_rows: list[dict[str, Any]] = field(default_factory=list)
    merged_rows: list[dict[str, Any]] = field(default_factory=list)
    original_top10: list[dict[str, Any]] = field(default_factory=list)
    missing_ai_stock_codes: list[str] = field(default_factory=list)
    missing_required_ai_columns: list[str] = field(default_factory=list)
    date_mismatch_codes: list[str] = field(default_factory=list)
    invalid_original_stock_codes: list[str] = field(default_factory=list)
    invalid_ai_stock_codes: list[str] = field(default_factory=list)

    @property
    def top10_merge_ready(self) -> bool:
        return (
            bool(self.original_top10)
            and not self.missing_ai_stock_codes
            and not self.missing_required_ai_columns
            and not self.date_mismatch_codes
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def merge_original_ranking_with_ai(
    original_rows: list[dict[str, Any]],
    ai_rows: list[dict[str, Any]],
    trade_date: str,
    top_n: int = 10,
    required_ai_columns: set[str] | None = None,
) -> FixedTop10MergeResult:
    trade_date = normalize_trade_date_text(trade_date)
    required = required_ai_columns or REQUIRED_AI_COLUMNS
    invalid_original: list[str] = []
    invalid_ai: list[str] = []
    date_mismatch: list[str] = []

    original_canonical = canonical_original_rows(original_rows, trade_date)
    seen_original = {row.get("stock_code") for row in original_canonical}
    for row in original_rows or []:
        code = normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("ts_code"))
        if not code:
            invalid_original.append(str(row.get("stock_code") or row.get("code") or ""))

    ai_by_code: dict[str, dict[str, Any]] = {}
    ai_columns = set(ai_rows[0].keys()) if ai_rows else set()
    missing_columns = sorted(required - ai_columns) if ai_rows else sorted(required)
    for row in ai_rows or []:
        code = normalize_stock_code(row.get("stock_code") or row.get("code") or row.get("ts_code"))
        if not code:
            invalid_ai.append(str(row.get("stock_code") or row.get("code") or ""))
            continue
        if _row_date(row, trade_date) != trade_date:
            date_mismatch.append(code)
            continue
        data = dict(row)
        data["stock_code"] = code
        data["code"] = code
        ai_by_code[code] = data

    merged: list[dict[str, Any]] = []
    for original in original_canonical:
        code = str(original.get("stock_code") or "")
        ai = ai_by_code.get(code, {})
        price = current_price(ai, original)
        merged_row = {
            "trade_date": trade_date,
            "stock_code": code,
            "code": code,
            "stock_name": ai.get("stock_name") or ai.get("name") or original.get("stock_name") or original.get("name") or "",
            "original_score": original_score(original),
            "original_rank": original_rank(original),
            "rank": original_rank(original),
            "position_adjustment_ratio": ai.get("position_adjustment_ratio") or ai.get("stored_position_adjustment_ratio") or 1.0,
            "target_weight": ai.get("target_weight") or ai.get("stored_target_weight") or "",
            "news_adjustment": ai.get("news_adjustment") or ai.get("news_adjustment_score") or 0.0,
            "user_adjustment": ai.get("user_adjustment") or ai.get("user_adjustment_score") or 0.0,
            "effective_news_adjustment": ai.get("effective_news_adjustment") if ai.get("effective_news_adjustment") not in [None, ""] else 0.0,
            "combined_adjustment": ai.get("combined_adjustment") or "",
            "current_price": price,
            "close": price,
            "stored_target_weight": ai.get("stored_target_weight", ai.get("target_weight", "")) if ai else "",
            "stored_position_adjustment_ratio": ai.get(
                "stored_position_adjustment_ratio",
                ai.get("position_adjustment_ratio", ""),
            )
            if ai
            else "",
        }
        merged_row.update({key: value for key, value in original.items() if key not in merged_row})
        merged_row.update({key: value for key, value in ai.items() if key not in {"trade_date", "stock_code", "code"} and key not in merged_row})
        merged.append(merged_row)

    top10 = select_fixed_original_top10(merged, top_n=top_n)
    missing_ai = [str(row.get("stock_code") or "") for row in top10 if str(row.get("stock_code") or "") not in ai_by_code]
    return FixedTop10MergeResult(
        trade_date=trade_date,
        original_rows=original_canonical,
        ai_rows=[dict(row) for row in ai_rows or []],
        merged_rows=merged,
        original_top10=top10,
        missing_ai_stock_codes=missing_ai,
        missing_required_ai_columns=missing_columns,
        date_mismatch_codes=sorted(set(date_mismatch)),
        invalid_original_stock_codes=invalid_original,
        invalid_ai_stock_codes=invalid_ai,
    )
