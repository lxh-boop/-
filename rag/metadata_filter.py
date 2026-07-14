from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from rag.schemas import RagChunk, RetrievalFilters
from rag.utils import ensure_list, normalize_date_text, parse_datetime


def _chunk_from_any(chunk: RagChunk | dict[str, Any]) -> RagChunk:
    return chunk if isinstance(chunk, RagChunk) else RagChunk.from_mapping(chunk)


def _comparable_datetime(value: Any):
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed
    china_standard_time = timezone(timedelta(hours=8))
    return parsed.astimezone(china_standard_time).replace(tzinfo=None)


def metadata_matches(
    chunk: RagChunk | dict[str, Any],
    filters: RetrievalFilters | dict[str, Any] | None = None,
) -> bool:
    if filters is None:
        return True
    filter_obj = filters if isinstance(filters, RetrievalFilters) else RetrievalFilters.from_mapping(filters)
    item = _chunk_from_any(chunk)
    meta = item.metadata or {}

    if filter_obj.stock_code:
        target = str(filter_obj.stock_code).split(".")[0].zfill(6)
        stock_codes = [str(code).split(".")[0].zfill(6) for code in ensure_list(item.stock_codes)]
        stock_codes += [
            str(code).split(".")[0].zfill(6)
            for code in ensure_list(meta.get("stock_code") or meta.get("stock_codes"))
        ]
        if target not in set(stock_codes):
            return False

    if filter_obj.stock_name:
        text = f"{item.chunk_text} {meta.get('stock_name', '')} {meta.get('stock_names', '')}"
        if str(filter_obj.stock_name) not in text:
            return False

    if filter_obj.industry and filter_obj.industry not in {item.industry, meta.get("industry")}:
        return False

    if filter_obj.concept:
        concepts = [str(v) for v in ensure_list(meta.get("concept") or meta.get("concepts"))]
        if filter_obj.concept not in concepts:
            return False

    if filter_obj.event_type and filter_obj.event_type != item.event_type:
        return False

    if filter_obj.source and filter_obj.source != item.source:
        return False

    if filter_obj.is_announcement is not None and bool(filter_obj.is_announcement) != bool(item.is_announcement):
        return False

    if filter_obj.min_importance_score is not None:
        score = item.importance_score if item.importance_score is not None else meta.get("importance_score")
        if score is None or float(score) < float(filter_obj.min_importance_score):
            return False

    if filter_obj.retention_level and filter_obj.retention_level != item.retention_level:
        return False

    if filter_obj.trade_date_start:
        if normalize_date_text(item.trade_date) < normalize_date_text(filter_obj.trade_date_start):
            return False

    if filter_obj.trade_date_end:
        if normalize_date_text(item.trade_date) > normalize_date_text(filter_obj.trade_date_end):
            return False

    if filter_obj.decision_time:
        published_at = _comparable_datetime(item.publish_time)
        decision_time = _comparable_datetime(filter_obj.decision_time)
        if published_at and decision_time and published_at > decision_time:
            return False

    return True


def filter_chunks(
    chunks: list[RagChunk | dict[str, Any]],
    filters: RetrievalFilters | dict[str, Any] | None = None,
) -> list[RagChunk]:
    return [_chunk_from_any(chunk) for chunk in chunks if metadata_matches(chunk, filters)]
