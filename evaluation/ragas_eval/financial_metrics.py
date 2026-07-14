from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from evaluation.ragas_eval.schemas import EvaluationCase, RetrievedContext, normalize_stock_code, parse_optional_datetime


INDIRECT_CONTEXT_MARKERS = {
    "industry",
    "market",
    "macro",
    "concept",
    "sector",
    "product",
    "supply_chain",
    "供应链",
    "行业",
    "市场",
    "宏观",
    "产品",
}

DIRECT_SOURCE_MARKERS = [
    "上市公司公告",
    "交易所公告",
    "公司公告",
    "公告",
    "上交所",
    "深交所",
    "北交所",
    "证监会",
    "监管",
]


def _metadata_text(context: RetrievedContext) -> str:
    meta = context.metadata or {}
    return " ".join(
        str(value or "").lower()
        for value in [
            context.source,
            context.title,
            meta.get("event_type"),
            meta.get("context_scope"),
            meta.get("evidence_type"),
            meta.get("mapping_method"),
            meta.get("industry"),
            meta.get("concept"),
        ]
    )


def _is_indirect_context(context: RetrievedContext) -> bool:
    text = _metadata_text(context)
    return any(marker.lower() in text for marker in INDIRECT_CONTEXT_MARKERS)


def _is_direct_evidence(context: RetrievedContext, target_stock_code: str) -> bool:
    meta = context.metadata or {}
    meta_text = _metadata_text(context)
    if bool(meta.get("is_announcement")):
        return True
    if any(marker in str(context.source or "") for marker in DIRECT_SOURCE_MARKERS):
        return True
    evidence_type = str(meta.get("evidence_type") or meta.get("context_scope") or "").lower()
    if evidence_type in {"company_direct", "direct_company_event", "direct_evidence"}:
        return True
    return bool(target_stock_code and target_stock_code in set(context.stock_codes) and not _is_indirect_context(context))


def _duplicate_key(context: RetrievedContext) -> str:
    if context.event_id:
        return f"event:{context.event_id}"
    if context.document_id:
        return f"document:{context.document_id}"
    if context.title and context.publish_time:
        return f"title_time:{context.title}|{context.publish_time.strftime('%Y-%m-%d %H')}"
    return f"chunk:{context.chunk_id}"


def future_leak_metrics(case: EvaluationCase, contexts: list[RetrievedContext]) -> dict[str, Any]:
    total = len(contexts)
    parsed_count = 0
    future_ids: list[str] = []
    missing_count = 0
    decision_time = case.decision_time
    for context in contexts:
        published_at = context.publish_time
        if published_at is None:
            published_at = parse_optional_datetime((context.metadata or {}).get("publish_time"))
        if published_at is None:
            missing_count += 1
            continue
        parsed_count += 1
        if published_at > decision_time:
            future_ids.append(context.chunk_id)
    return {
        "future_leak_definition": "publish_time > decision_time / contexts with parseable publish_time",
        "future_leak_count": len(future_ids),
        "future_leak_rate": len(future_ids) / parsed_count if parsed_count else 0.0,
        "future_leak_chunk_ids": future_ids,
        "publish_time_parseable_count": parsed_count,
        "missing_publish_time_count": missing_count,
        "missing_publish_time_rate": missing_count / total if total else 0.0,
    }


def wrong_stock_metrics(case: EvaluationCase, contexts: list[RetrievedContext]) -> dict[str, Any]:
    target = normalize_stock_code(case.stock_code)
    allowed = {normalize_stock_code(item) for item in case.allowed_related_stock_codes if normalize_stock_code(item)}
    wrong_ids: list[str] = []
    explicit_stock_context_count = 0
    for context in contexts:
        codes = {normalize_stock_code(item) for item in context.stock_codes if normalize_stock_code(item)}
        if not codes:
            continue
        explicit_stock_context_count += 1
        if target not in codes and not (codes & allowed) and not _is_indirect_context(context):
            wrong_ids.append(context.chunk_id)
    return {
        "wrong_stock_definition": "explicit stock-bound context excluding target/allowed related stocks and non-industry contexts",
        "explicit_stock_context_count": explicit_stock_context_count,
        "wrong_stock_count": len(wrong_ids),
        "wrong_stock_rate": len(wrong_ids) / explicit_stock_context_count if explicit_stock_context_count else 0.0,
        "wrong_stock_chunk_ids": wrong_ids,
    }


def duplicate_event_metrics(contexts: list[RetrievedContext]) -> dict[str, Any]:
    keys = [_duplicate_key(context) for context in contexts]
    counts = Counter(keys)
    duplicate_count = sum(max(0, count - 1) for count in counts.values())
    duplicate_ids: list[str] = []
    seen: set[str] = set()
    for context, key in zip(contexts, keys):
        if key in seen:
            duplicate_ids.append(context.chunk_id)
        seen.add(key)
    return {
        "duplicate_event_definition": "same event_id first, then document_id, then conservative title+hour",
        "duplicate_event_count": duplicate_count,
        "duplicate_event_rate": duplicate_count / len(contexts) if contexts else 0.0,
        "duplicate_event_chunk_ids": duplicate_ids,
    }


def direct_evidence_metrics(case: EvaluationCase, contexts: list[RetrievedContext]) -> dict[str, Any]:
    direct_ids = [
        context.chunk_id
        for context in contexts
        if _is_direct_evidence(context, normalize_stock_code(case.stock_code))
    ]
    return {
        "direct_evidence_definition": "company/exchange/regulatory announcement or direct company event metadata",
        "direct_evidence_count": len(direct_ids),
        "direct_evidence_rate": len(direct_ids) / len(contexts) if contexts else 0.0,
        "direct_evidence_chunk_ids": direct_ids,
    }


def unsupported_position_reason_metric(response: str) -> dict[str, Any]:
    text = str(response or "")
    position_terms = ["仓位", "减仓", "加仓", "持仓", "权重", "配置", "调仓"]
    if not any(term in text for term in position_terms):
        return {
            "unsupported_position_reason_rate": None,
            "unsupported_position_reason_status": "not_applicable",
            "unsupported_position_reason_definition": "only evaluated when response includes position-adjustment reasons",
        }
    return {
        "unsupported_position_reason_rate": None,
        "unsupported_position_reason_status": "not_available",
        "unsupported_position_reason_definition": "requires claim-level grounding or existing structured reason fields; not approximated by keywords",
    }


def calculate_financial_metrics(
    case: EvaluationCase,
    contexts: list[RetrievedContext],
    *,
    response: str = "",
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    metrics.update(future_leak_metrics(case, contexts))
    metrics.update(wrong_stock_metrics(case, contexts))
    metrics.update(duplicate_event_metrics(contexts))
    metrics.update(direct_evidence_metrics(case, contexts))
    metrics.update(unsupported_position_reason_metric(response))
    return metrics
