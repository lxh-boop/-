from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipelines.fixed_top10_inputs import REQUIRED_AI_COLUMNS, merge_original_ranking_with_ai
from pipelines.historical_prediction_loader import HistoricalPredictionResult
from pipelines.replay_normalization import normalize_stock_code, normalize_trade_date_text, trade_date_token


REQUIRED_AI_ADJUSTMENT_COLUMNS = REQUIRED_AI_COLUMNS


@dataclass(frozen=True)
class HistoricalAIAdjustmentResult:
    trade_date: str
    status: str
    records: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    warnings: list[str] = field(default_factory=list)
    mismatch_reasons: list[str] = field(default_factory=list)
    full_record_count: int = 0
    original_top10_codes: list[str] = field(default_factory=list)


def _date_token(trade_date: str) -> str:
    return trade_date_token(trade_date)


def _stock_code(value: Any) -> str:
    return normalize_stock_code(value)


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


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _ai_adjustment_candidates(output_dir: str | Path, user_id: str, trade_date: str) -> list[Path]:
    root = Path(output_dir)
    token = _date_token(trade_date)
    paths = [
        root / "users" / str(user_id) / "recommendations" / f"final_recommendations_{token}.csv",
        root / "users" / str(user_id) / "recommendations" / f"final_recommendations_{trade_date}.csv",
        root / "recommendations" / "history" / f"final_recommendations_{token}.csv",
        root / "recommendations" / f"final_recommendations_{token}.csv",
    ]
    return [path for path in paths if path.exists() and path.name != "final_recommendations_latest.csv"]


def _prediction_lookup(prediction: HistoricalPredictionResult) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for item in prediction.predictions:
        data = item.to_dict() if hasattr(item, "to_dict") else dict(item)
        code = _stock_code(data.get("stock_code") or data.get("code"))
        if code:
            lookup[code] = data
    return lookup


def _canonical_record(row: dict[str, Any], ranking_row: dict[str, Any] | None, trade_date: str, source: Path) -> dict[str, Any]:
    data = dict(row)
    code = _stock_code(data.get("stock_code") or data.get("code"))
    rank = _safe_int(
        data.get("final_rank")
        or data.get("rank")
        or data.get("original_rank")
        or data.get("original_pred_rank")
        or (ranking_row or {}).get("original_rank")
        or (ranking_row or {}).get("rank"),
        9999,
    )
    original_rank = _safe_int(
        data.get("original_rank")
        or data.get("original_pred_rank")
        or (ranking_row or {}).get("original_rank")
        or (ranking_row or {}).get("pred_rank")
        or (ranking_row or {}).get("rank"),
        rank,
    )
    original_score = _safe_float(
        data.get("original_score")
        or data.get("original_pred_score")
        or (ranking_row or {}).get("pred_score")
        or (ranking_row or {}).get("score"),
        0.0,
    )
    current_price = _safe_float(
        data.get("current_price")
        or data.get("close")
        or (ranking_row or {}).get("current_price")
        or (ranking_row or {}).get("close"),
        0.0,
    )
    data.update(
        {
            "trade_date": trade_date,
            "stock_code": code,
            "code": code,
            "stock_name": data.get("stock_name") or data.get("name") or (ranking_row or {}).get("stock_name") or (ranking_row or {}).get("name") or "",
            "original_rank": original_rank,
            "original_score": original_score,
            "original_pred_rank": original_rank,
            "original_pred_score": original_score,
            "rank": rank,
            "final_rank": rank,
            "current_price": current_price,
            "close": current_price,
            "stored_target_weight": data.get("stored_target_weight", data.get("target_weight", "")),
            "stored_final_score": data.get("stored_final_score", data.get("final_score", data.get("score", ""))),
            "stored_final_rank": data.get("stored_final_rank", rank),
            
            "stored_position_adjustment_ratio": data.get(
                "stored_position_adjustment_ratio",
                data.get("position_adjustment_ratio", ""),
            ),
            "source_path": str(source),
            "decision_created_at": data.get("decision_created_at") or data.get("created_at") or "",
        }
    )
    return data


def _validate_alignment(
    rows: list[dict[str, Any]],
    prediction: HistoricalPredictionResult,
    trade_date: str,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    prediction_by_code = _prediction_lookup(prediction)
    reasons: list[str] = []
    aligned: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = _stock_code(row.get("stock_code") or row.get("code"))
        if not code:
            reasons.append("ai adjustment row missing stock_code")
            continue
        if str(row.get("trade_date") or row.get("date") or trade_date)[:10] != trade_date:
            reasons.append(f"{code}: ai adjustment trade_date mismatch")
            continue
        ranking = prediction_by_code.get(code)
        if not ranking:
            reasons.append(f"{code}: ai adjustment stock_code not found in original ranking")
            continue
        ai_rank = _safe_int(row.get("original_rank") or row.get("original_pred_rank") or row.get("rank"), 0)
        original_rank = _safe_int(ranking.get("original_rank") or ranking.get("pred_rank") or ranking.get("rank"), 0)
        if ai_rank and original_rank and ai_rank != original_rank:
            reasons.append(f"{code}: original rank mismatch ai={ai_rank} ranking={original_rank}")
            continue
        ai_score = _safe_float(row.get("original_score") or row.get("original_pred_score"), 0.0)
        original_score = _safe_float(ranking.get("pred_score") or ranking.get("score"), 0.0)
        if ai_score and original_score and abs(ai_score - original_score) > 1e-6:
            reasons.append(f"{code}: original score mismatch")
            continue
        aligned[code] = ranking
    return reasons, aligned


def load_historical_ai_adjustments(
    trade_date: str,
    prediction: HistoricalPredictionResult,
    user_id: str = "default",
    output_dir: str | Path = "outputs",
    top_k: int = 30,
    full_results: bool = False,
) -> HistoricalAIAdjustmentResult:
    trade_date = normalize_trade_date_text(trade_date)
    warnings: list[str] = []
    if prediction.status != "success":
        return HistoricalAIAdjustmentResult(
            trade_date=trade_date,
            status="missing_original_ranking",
            warnings=[f"original ranking missing for {trade_date}; ai adjustment was not loaded."],
        )
    for path in _ai_adjustment_candidates(output_dir, user_id, trade_date):
        rows = _read_csv(path)
        if not rows:
            continue
        prediction_rows = [
            item.to_dict() if hasattr(item, "to_dict") else dict(item)
            for item in prediction.predictions
        ]
        merged = merge_original_ranking_with_ai(
            prediction_rows,
            rows,
            trade_date=trade_date,
            top_n=10,
            required_ai_columns=REQUIRED_AI_ADJUSTMENT_COLUMNS,
        )
        if merged.missing_required_ai_columns:
            return HistoricalAIAdjustmentResult(
                trade_date=trade_date,
                status="missing_ai_adjustment_fields",
                source=str(path),
                warnings=[f"missing ai adjustment columns: {merged.missing_required_ai_columns}"],
                full_record_count=len(rows),
                original_top10_codes=[str(item.get("stock_code") or "") for item in merged.original_top10],
            )
        if merged.date_mismatch_codes or merged.missing_ai_stock_codes:
            reasons = []
            if merged.date_mismatch_codes:
                reasons.append(f"ai adjustment trade_date mismatch: {merged.date_mismatch_codes}")
            if merged.missing_ai_stock_codes:
                reasons.append(f"missing ai adjustment for original Top10: {merged.missing_ai_stock_codes}")
            return HistoricalAIAdjustmentResult(
                trade_date=trade_date,
                status="result_mismatch",
                source=str(path),
                warnings=warnings,
                mismatch_reasons=reasons,
                full_record_count=len(rows),
                original_top10_codes=[str(item.get("stock_code") or "") for item in merged.original_top10],
            )
        ai_codes = {_stock_code(row.get("stock_code") or row.get("code")) for row in rows}
        canonical = [
            {
                **row,
                "source_path": str(path),
                "decision_created_at": row.get("decision_created_at") or row.get("created_at") or "",
            }
            for row in merged.merged_rows
            if _stock_code(row.get("stock_code") or row.get("code")) in ai_codes
        ]
        canonical = sorted(
            canonical,
            key=lambda item: (
                _safe_int(item.get("original_rank") or item.get("rank"), 9999),
                -_safe_float(item.get("final_score"), 0.0),
                str(item.get("stock_code") or ""),
            ),
        )
        if not full_results and int(top_k or 0) > 0:
            canonical = canonical[: max(1, int(top_k or 30))]
        if not canonical:
            return HistoricalAIAdjustmentResult(
                trade_date=trade_date,
                status="result_mismatch",
                source=str(path),
                mismatch_reasons=["no ai adjustment rows aligned with original ranking"],
                full_record_count=len(rows),
                original_top10_codes=[str(item.get("stock_code") or "") for item in merged.original_top10],
            )
        return HistoricalAIAdjustmentResult(
            trade_date=trade_date,
            status="success",
            records=canonical,
            source=str(path),
            warnings=warnings,
            full_record_count=len(rows),
            original_top10_codes=[str(item.get("stock_code") or "") for item in merged.original_top10],
        )
    return HistoricalAIAdjustmentResult(
        trade_date=trade_date,
        status="missing_ai_adjustment",
        warnings=[f"missing stored ai adjustment for {trade_date}; no backfill recomputation was attempted."],
    )
