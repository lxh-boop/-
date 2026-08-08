from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from rag.utils import ensure_list


def _json_list(value: Any) -> list[Any]:
    if value in [None, ""]:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            loaded = json.loads(text)
            return list(loaded) if isinstance(loaded, list) else [loaded]
        except Exception:
            return ensure_list(value)
    return ensure_list(value)


def _json_dict(value: Any) -> dict[str, Any]:
    if value in [None, ""]:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return dict(loaded) if isinstance(loaded, dict) else {}
        except Exception:
            return {}
    return {}


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    news_id: str
    chunk_index: int
    chunk_text: str
    title: str = ""
    source: str = ""
    publish_time: str = ""
    trade_date: str = ""
    stock_codes: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    industry: str = ""
    event_type: str = ""
    is_announcement: bool = False
    content_level: str = "title_only"
    url: str = ""
    section_title: str = ""
    importance_score: float | None = None
    retention_level: str = "hot"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "RagChunk":
        stock_codes = data.get("stock_codes")
        if stock_codes in [None, ""]:
            stock_codes = data.get("stock_codes_json")
        if stock_codes in [None, ""]:
            stock_codes = data.get("stock_code")

        metadata = _json_dict(data.get("metadata"))
        if not metadata:
            metadata = _json_dict(data.get("metadata_json"))

        entities = data.get("entities")
        if entities in [None, ""]:
            entities = data.get("entities_json")
        entities_list = [
            dict(item) if isinstance(item, dict) else {"type": "entity", "name": str(item)}
            for item in _json_list(entities)
            if item not in [None, ""]
        ]

        normalized_codes = []
        for code in _json_list(stock_codes):
            text = str(code or "").split(".")[0]
            digits = "".join(ch for ch in text if ch.isdigit())
            if digits:
                normalized_codes.append(digits[-6:].zfill(6))
        normalized_codes = list(dict.fromkeys(normalized_codes))

        title = str(data.get("title") or metadata.get("title") or data.get("section_title") or "")
        return cls(
            chunk_id=str(data.get("chunk_id") or ""),
            news_id=str(data.get("news_id") or ""),
            chunk_index=int(data.get("chunk_index") or 0),
            chunk_text=str(data.get("chunk_text") or ""),
            title=title,
            source=str(data.get("source") or ""),
            publish_time=str(data.get("publish_time") or ""),
            trade_date=str(data.get("trade_date") or ""),
            stock_codes=normalized_codes,
            entities=entities_list,
            industry=str(data.get("industry") or ""),
            event_type=str(data.get("event_type") or ""),
            is_announcement=bool(data.get("is_announcement")),
            content_level=str(data.get("content_level") or "title_only"),
            url=str(data.get("url") or ""),
            section_title=str(data.get("section_title") or ""),
            importance_score=(
                float(data["importance_score"])
                if data.get("importance_score") not in [None, ""]
                else None
            ),
            retention_level=str(data.get("retention_level") or "hot"),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_database_record(self) -> dict[str, Any]:
        metadata = {"title": self.title, **dict(self.metadata or {})}
        return {
            "chunk_id": self.chunk_id,
            "news_id": self.news_id,
            "chunk_index": self.chunk_index,
            "chunk_text": self.chunk_text,
            "title": self.title,
            "section_title": self.section_title,
            "source": self.source,
            "publish_time": self.publish_time,
            "trade_date": self.trade_date,
            "stock_code": self.stock_codes[0] if self.stock_codes else "",
            "stock_codes_json": json.dumps(self.stock_codes, ensure_ascii=False),
            "entities_json": json.dumps(self.entities, ensure_ascii=False),
            "metadata_json": json.dumps(metadata, ensure_ascii=False, sort_keys=True),
            "industry": self.industry,
            "event_type": self.event_type,
            "is_announcement": int(self.is_announcement),
            "content_level": self.content_level,
            "importance_score": self.importance_score,
            "retention_level": self.retention_level,
        }


@dataclass(frozen=True)
class RetrievalFilters:
    stock_code: str | None = None
    stock_name: str | None = None
    industry: str | None = None
    concept: str | None = None
    event_type: str | None = None
    source: str | None = None
    decision_time: str | None = None
    trade_date_start: str | None = None
    trade_date_end: str | None = None
    is_announcement: bool | None = None
    min_importance_score: float | None = None
    retention_level: str | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "RetrievalFilters":
        return cls(**(data or {}))

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class RetrievalResult:
    chunk_id: str
    news_id: str
    chunk_text: str
    bm25_score: float = 0.0
    dense_score: float = 0.0
    hybrid_score: float = 0.0
    rerank_score: float = 0.0
    final_rank: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
