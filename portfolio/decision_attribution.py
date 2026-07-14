from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from portfolio.schemas import PAPER_TRADING_DISCLAIMER


ATTRIBUTION_SCHEMA_VERSION = "decision_attribution_v1"
READ_ONLY_MODE = "read_only_attribution"
FORMULA_TOLERANCE = 1e-6


def _stock_code(value: Any) -> str:
    text = str(value or "").strip().split(".")[0]
    return text.zfill(6) if text else ""


def _date_token(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:8]


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


def _jsonish(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if value in [None, ""]:
        return [] if value == "" else value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("[", "{")):
            try:
                return json.loads(text)
            except Exception:
                return value
    return value


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        rows = payload.get("records") or payload.get("rows") or payload.get("decisions")
        if isinstance(rows, list):
            return [dict(item) for item in rows if isinstance(item, dict)]
        return [payload]
    return []


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as file:
            return [dict(row) for row in csv.DictReader(file)]
    except Exception:
        return []


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    if path.suffix.lower() == ".json":
        return _read_json_rows(path)
    if path.suffix.lower() == ".csv":
        return _read_csv_rows(path)
    return []


def _read_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _recommendation_candidates(user_id: str, output_dir: str | Path, trade_date: str | None) -> list[Path]:
    root = Path(output_dir)
    token = _date_token(trade_date)
    user_dir = root / "users" / str(user_id) / "recommendations"
    global_dir = root / "recommendations"
    dated_names: list[str] = []
    if token:
        dated_names.extend(
            [
                f"final_recommendations_{token}.json",
                f"final_recommendations_{token}.csv",
            ]
        )
    if trade_date:
        dated_names.extend(
            [
                f"final_recommendations_{trade_date}.json",
                f"final_recommendations_{trade_date}.csv",
            ]
        )
    names = dated_names + ["final_recommendations_latest.json", "final_recommendations_latest.csv"]
    return _dedupe_paths([directory / name for directory in [user_dir, global_dir] for name in names])


def _decision_candidates(user_id: str, output_dir: str | Path, trade_date: str | None) -> list[Path]:
    root = Path(output_dir) / "portfolio" / str(user_id)
    token = _date_token(trade_date)
    candidates: list[Path] = []
    if token:
        history = root / "history" / "decisions"
        candidates.append(history / f"ai_paper_decisions_{token}.json")
        candidates.extend(sorted(history.glob(f"ai_paper_decisions_{token}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    candidates.append(root / "ai_paper_decisions_latest.json")
    return _dedupe_paths(candidates)


def _find_row(rows: list[dict[str, Any]], stock_code: str, trade_date: str | None = None) -> dict[str, Any] | None:
    normalized = _stock_code(stock_code)
    date_text = str(trade_date or "")
    matches = [
        row
        for row in rows
        if _stock_code(row.get("stock_code") or row.get("code")) == normalized
    ]
    if date_text:
        dated = [row for row in matches if str(row.get("trade_date") or row.get("date") or "") == date_text]
        if dated:
            return dict(dated[0])
    return dict(matches[0]) if matches else None


def _load_recommendation(
    user_id: str,
    stock_code: str,
    output_dir: str | Path,
    trade_date: str | None,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    searched: list[str] = []
    for path in _recommendation_candidates(user_id, output_dir, trade_date):
        searched.append(str(path))
        row = _find_row(_read_rows(path), stock_code, trade_date)
        if row:
            for key in ["evidence_news_ids", "evidence_chunk_ids", "triggered_rules", "score_breakdown"]:
                if key in row:
                    row[key] = _jsonish(row.get(key))
            return row, str(path), searched
    return None, "", searched


def _load_decision_from_database(
    user_id: str,
    stock_code: str,
    trade_date: str | None,
    db_path: str | Path | None,
) -> tuple[dict[str, Any] | None, str]:
    if not db_path:
        return None, ""
    try:
        from database.repositories import PortfolioRepository

        rows = PortfolioRepository(db_path).list_paper_decisions(user_id=user_id, trade_date=trade_date)
    except Exception:
        return None, ""
    row = _find_row(rows, stock_code, trade_date)
    return row, f"database:{db_path}:paper_decision_log" if row else ""


def _load_paper_decision(
    user_id: str,
    stock_code: str,
    output_dir: str | Path,
    trade_date: str | None,
    db_path: str | Path | None,
) -> tuple[dict[str, Any] | None, str, list[str]]:
    searched: list[str] = []
    for path in _decision_candidates(user_id, output_dir, trade_date):
        searched.append(str(path))
        row = _find_row(_read_rows(path), stock_code, trade_date)
        if row:
            return row, str(path), searched
    row, source = _load_decision_from_database(user_id, stock_code, trade_date, db_path)
    if row:
        searched.append(source)
        return row, source, searched
    return None, "", searched


def _load_diagnostics(user_id: str, output_dir: str | Path) -> tuple[dict[str, Any], str]:
    path = Path(output_dir) / "portfolio" / str(user_id) / "paper_execution_diagnostics_latest.json"
    return _read_json_dict(path), str(path) if path.exists() else ""


def _matching_allocation_items(stock_code: str, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = _stock_code(stock_code)
    items: list[dict[str, Any]] = []
    for section in ["allocation_details", "removed_candidates", "permission_blocked_candidates", "backup_candidates", "replacement_candidates"]:
        for item in diagnostics.get(section) or []:
            if isinstance(item, dict) and _stock_code(item.get("stock_code")) == normalized:
                record = dict(item)
                record["_diagnostic_section"] = section
                items.append(record)
    return items


def _lot_rounds_for_stock(stock_code: str, diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = _stock_code(stock_code)
    rounds: list[dict[str, Any]] = []
    for item in diagnostics.get("lot_execution_rounds") or []:
        if not isinstance(item, dict):
            continue
        code_lists = []
        for key in [
            "candidate_stock_codes",
            "candidate_codes_before",
            "candidate_codes_after",
            "unaffordable_stock_codes",
            "unaffordable_codes",
        ]:
            values = item.get(key) or []
            if isinstance(values, list):
                code_lists.extend(_stock_code(value) for value in values)
        weight_maps = []
        for key in ["weights_before", "weights_after", "target_weights_before", "target_weights_after", "redistributed_weights"]:
            values = item.get(key) or {}
            if isinstance(values, dict):
                weight_maps.extend(_stock_code(key) for key in values)
        if normalized in code_lists or normalized in weight_maps or _stock_code(item.get("removed_stock_code")) == normalized:
            rounds.append(
                {
                    "round_no": item.get("round_no"),
                    "removed_stock_code": _stock_code(item.get("removed_stock_code")),
                    "removed_reason": item.get("removed_reason", ""),
                    "released_weight": item.get("released_weight", 0.0),
                    "target_weight_before": (item.get("target_weights_before") or {}).get(normalized),
                    "target_weight_after": (item.get("target_weights_after") or {}).get(normalized),
                    "redistributed_weight": (item.get("redistributed_weights") or {}).get(normalized),
                }
            )
    return rounds


def _formula_check(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"status": "missing_recommendation"}
    news = _safe_float(row.get("news_adjustment"), 0.0)
    user = _safe_float(row.get("user_adjustment"), 0.0)
    reliability = _safe_float(row.get("ai_reliability_weight"), 0.0)
    stored_effective = _safe_float(row.get("effective_news_adjustment"), 0.0)
    stored_combined = _safe_float(row.get("combined_adjustment"), 0.0)
    stored_ratio = _safe_float(row.get("position_adjustment_ratio"), 1.0)
    expected_effective = reliability * news
    expected_combined = expected_effective + user
    expected_ratio = max(0.0, min(2.0, 1.0 + expected_combined))
    return {
        "status": "stored_formula_check",
        "note": "只核对落盘字段是否符合既有公式，不用该结果重新生成仓位或交易。",
        "inputs": {
            "news_adjustment": news,
            "user_adjustment": user,
            "ai_reliability_weight": reliability,
        },
        "expected": {
            "effective_news_adjustment": expected_effective,
            "combined_adjustment": expected_combined,
            "position_adjustment_ratio": expected_ratio,
        },
        "stored": {
            "effective_news_adjustment": stored_effective,
            "combined_adjustment": stored_combined,
            "position_adjustment_ratio": stored_ratio,
        },
        "effective_news_adjustment_matches": abs(stored_effective - expected_effective) <= FORMULA_TOLERANCE,
        "combined_adjustment_matches": abs(stored_combined - expected_combined) <= FORMULA_TOLERANCE,
        "position_adjustment_ratio_matches": abs(stored_ratio - expected_ratio) <= FORMULA_TOLERANCE,
    }


def _compact_recommendation(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "stock_code": _stock_code(row.get("stock_code") or row.get("code")),
        "stock_name": row.get("stock_name") or row.get("name") or "",
        "trade_date": row.get("trade_date") or row.get("date") or "",
        "model_name": row.get("model_name") or "",
        "original_rank": _safe_int(row.get("original_rank") or row.get("original_pred_rank") or row.get("rank")),
        "original_score": _safe_float(row.get("original_score") or row.get("original_pred_score") or row.get("score")),
        "news_adjustment": _safe_float(row.get("news_adjustment")),
        "user_adjustment": _safe_float(row.get("user_adjustment")),
        "effective_news_adjustment": _safe_float(row.get("effective_news_adjustment")),
        "combined_adjustment": _safe_float(row.get("combined_adjustment")),
        "ai_reliability_weight": _safe_float(row.get("ai_reliability_weight")),
        "position_adjustment_ratio": _safe_float(row.get("position_adjustment_ratio"), 1.0),
        "original_target_weight": _safe_float(row.get("original_target_weight")),
        "target_weight": _safe_float(row.get("target_weight")),
        "current_price": _safe_float(row.get("current_price")),
        "reason": row.get("reason") or "",
        "risk_warning": row.get("risk_warning") or "",
        "evidence_news_ids": _jsonish(row.get("evidence_news_ids")) or [],
        "evidence_chunk_ids": _jsonish(row.get("evidence_chunk_ids")) or [],
        "triggered_rules": _jsonish(row.get("triggered_rules")) or [],
        "score_breakdown": _jsonish(row.get("score_breakdown")) or {},
    }


def _compact_decision(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    return {
        "decision_id": row.get("decision_id") or "",
        "trade_date": row.get("trade_date") or "",
        "decision_time": row.get("decision_time") or "",
        "stock_code": _stock_code(row.get("stock_code")),
        "stock_name": row.get("stock_name") or "",
        "paper_action": row.get("paper_action") or row.get("action") or "",
        "target_weight": _safe_float(row.get("target_weight")),
        "current_weight": _safe_float(row.get("current_weight")),
        "order_quantity": _safe_float(row.get("order_quantity") or row.get("quantity")),
        "order_amount": _safe_float(row.get("order_amount")),
        "executed_price": _safe_float(row.get("executed_price")),
        "total_fee": _safe_float(row.get("total_fee")),
        "net_cash_change": _safe_float(row.get("net_cash_change")),
        "original_rank": _safe_int(row.get("original_rank")),
        "original_score": _safe_float(row.get("original_score")),
        "news_adjustment": _safe_float(row.get("news_adjustment")),
        "user_adjustment": _safe_float(row.get("user_adjustment")),
        "effective_news_adjustment": _safe_float(row.get("effective_news_adjustment")),
        "combined_adjustment": _safe_float(row.get("combined_adjustment")),
        "position_adjustment_ratio": _safe_float(row.get("position_adjustment_ratio"), 1.0),
        "reason": row.get("reason") or "",
        "risk_warning": row.get("risk_warning") or "",
        "triggered_rules": row.get("triggered_rules") or "",
        "job_id": row.get("job_id") or "",
        "run_id": row.get("run_id") or "",
        "execution_source": row.get("execution_source") or "",
    }


def explain_stock_decision_attribution(
    user_id: str,
    stock_code: str,
    trade_date: str | None = None,
    output_dir: str | Path = "outputs",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return a read-only explanation built only from persisted recommendation and paper decision results."""

    normalized = _stock_code(stock_code)
    warnings: list[str] = []
    recommendation, rec_source, rec_searched = _load_recommendation(user_id, normalized, output_dir, trade_date)
    paper_decision, decision_source, decision_searched = _load_paper_decision(
        user_id,
        normalized,
        output_dir,
        trade_date,
        db_path,
    )
    diagnostics, diagnostics_source = _load_diagnostics(user_id, output_dir)
    allocation_items = _matching_allocation_items(normalized, diagnostics)
    lot_rounds = _lot_rounds_for_stock(normalized, diagnostics)

    if not recommendation:
        warnings.append("未找到该股票的已保存最终推荐结果；归因不会重新生成模型或AI调整。")
    if not paper_decision:
        warnings.append("未找到该股票的模拟盘决策结果；归因只展示可找到的推荐与诊断。")
    if not diagnostics:
        warnings.append("未找到最新模拟盘执行诊断；无法展示一手约束和权重分配细节。")
    elif trade_date and diagnostics_source and paper_decision and str(paper_decision.get("trade_date") or "") != str(trade_date):
        warnings.append("最新执行诊断可能不是所选交易日；请以历史回放审计为准。")

    formal = _compact_recommendation(recommendation)
    decision = _compact_decision(paper_decision)
    evidence_news = formal.get("evidence_news_ids") or _jsonish((recommendation or {}).get("evidence_news_ids")) or []
    evidence_chunks = formal.get("evidence_chunk_ids") or _jsonish((recommendation or {}).get("evidence_chunk_ids")) or []

    payload = {
        "schema_version": ATTRIBUTION_SCHEMA_VERSION,
        "mode": READ_ONLY_MODE,
        "user_id": str(user_id),
        "stock_code": normalized,
        "trade_date": str(trade_date or formal.get("trade_date") or decision.get("trade_date") or ""),
        "sources": {
            "recommendation": rec_source,
            "paper_decision": decision_source,
            "diagnostics": diagnostics_source,
            "searched_recommendations": rec_searched,
            "searched_paper_decisions": decision_searched,
        },
        "formal_recommendation": formal,
        "paper_decision": decision,
        "allocation_trace": {
            "strategy_mode": diagnostics.get("strategy_mode", ""),
            "base_weight_note": diagnostics.get("base_weight_note", ""),
            "top10_target_ratio": diagnostics.get("top10_target_ratio", diagnostics.get("target_ratio")),
            "minimum_cash_ratio": diagnostics.get("minimum_cash_ratio"),
            "maximum_final_position_weight": diagnostics.get("maximum_final_position_weight"),
            "diagnostic_items": allocation_items,
            "lot_execution_rounds": lot_rounds,
        },
        "evidence_trace": {
            "evidence_news_ids": evidence_news if isinstance(evidence_news, list) else [evidence_news],
            "evidence_chunk_ids": evidence_chunks if isinstance(evidence_chunks, list) else [evidence_chunks],
            "source_reason": formal.get("reason") or decision.get("reason") or "",
        },
        "rules_trace": {
            "triggered_rules": formal.get("triggered_rules") or decision.get("triggered_rules") or "",
            "risk_warning": formal.get("risk_warning") or decision.get("risk_warning") or "",
            "cannot_execute_reason": (allocation_items[0].get("cannot_execute_reason") if allocation_items else ""),
        },
        "formula_check": _formula_check(recommendation),
        "traceability_chain": [
            "stored_final_recommendation",
            "stored_news_user_reliability_adjustment",
            "stored_paper_allocation_diagnostics",
            "stored_paper_decision_execution",
        ],
        "warnings": warnings,
        "disclaimer": PAPER_TRADING_DISCLAIMER,
    }
    return payload


def render_decision_attribution_markdown(payload: dict[str, Any]) -> str:
    formal = payload.get("formal_recommendation") or {}
    decision = payload.get("paper_decision") or {}
    allocation = payload.get("allocation_trace") or {}
    evidence = payload.get("evidence_trace") or {}
    rules = payload.get("rules_trace") or {}
    formula = payload.get("formula_check") or {}
    lines = [
        f"### {payload.get('stock_code', '')} {formal.get('stock_name') or decision.get('stock_name') or ''}",
        "",
        f"- 归因模式：{payload.get('mode', READ_ONLY_MODE)}，只读取已保存结果，不重新生成模型、RAG 或交易。",
        f"- 交易日期：{payload.get('trade_date', '')}",
        f"- 原始排名/分数：{formal.get('original_rank', '')} / {formal.get('original_score', '')}",
        f"- 新闻/用户/有效新闻/综合调整：{formal.get('news_adjustment', 0)} / {formal.get('user_adjustment', 0)} / {formal.get('effective_news_adjustment', 0)} / {formal.get('combined_adjustment', 0)}",
        f"- 仓位调整比例：{formal.get('position_adjustment_ratio', '')}，推荐目标仓位：{formal.get('target_weight', '')}",
        f"- 模拟盘动作：{decision.get('paper_action', '')}，当前仓位：{decision.get('current_weight', '')}，执行目标仓位：{decision.get('target_weight', '')}",
        f"- 执行数量/金额/费用：{decision.get('order_quantity', '')} / {decision.get('order_amount', '')} / {decision.get('total_fee', '')}",
        f"- 分配策略：{allocation.get('strategy_mode', '')}；{allocation.get('base_weight_note', '')}",
        f"- 规则与风险：{rules.get('triggered_rules', '') or '无'}；{rules.get('risk_warning', '') or '无'}",
        f"- 证据 news_id：{json.dumps(evidence.get('evidence_news_ids') or [], ensure_ascii=False)}",
        f"- 证据 chunk_id：{json.dumps(evidence.get('evidence_chunk_ids') or [], ensure_ascii=False)}",
        f"- 公式核对：effective={formula.get('effective_news_adjustment_matches')}, combined={formula.get('combined_adjustment_matches')}, ratio={formula.get('position_adjustment_ratio_matches')}",
    ]
    lot_rounds = allocation.get("lot_execution_rounds") or []
    if lot_rounds:
        lines.append(f"- 一手约束相关轮次：{json.dumps(lot_rounds, ensure_ascii=False)}")
    warnings = payload.get("warnings") or []
    if warnings:
        lines.append(f"- 归因告警：{json.dumps(warnings, ensure_ascii=False)}")
    lines.extend(["", str(payload.get("disclaimer") or PAPER_TRADING_DISCLAIMER)])
    return "\n".join(lines)
