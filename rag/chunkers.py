from __future__ import annotations

import re
from typing import Any

from rag.schemas import RagChunk
from rag.utils import clean_text, ensure_list, stable_id


SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；;!?])")
ANNOUNCEMENT_HEADING_RE = re.compile(
    r"(?m)^(?P<title>(?:[一二三四五六七八九十]+、[^\n]{1,60}|（[一二三四五六七八九十]+）[^\n]{1,60}|风险提示|对公司的影响|合同主要内容|业绩变动原因))"
)


def split_chinese_sentences(text: str) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    parts = [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]
    return parts or [text]


def build_sentence_chunks(
    sentences: list[str],
    max_chars: int = 700,
    overlap_chars: int = 80,
) -> list[str]:
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = clean_text(sentence)
        if not sentence:
            continue
        if current and len(current) + len(sentence) > max_chars:
            chunks.append(current)
            current = current[-overlap_chars:] if overlap_chars > 0 else ""
        current = clean_text(f"{current}{sentence}")
    if current:
        chunks.append(current)
    return chunks


def _base_metadata(item: dict[str, Any]) -> dict[str, Any]:
    stock_codes = item.get("stock_codes", item.get("stock_code", []))
    return {
        "news_id": str(item.get("news_id") or stable_id(item.get("title"), item.get("publish_time"), prefix="news_")),
        "source": str(item.get("source") or ""),
        "publish_time": str(item.get("publish_time") or ""),
        "trade_date": str(item.get("trade_date") or ""),
        "stock_codes": [str(code).split(".")[0].zfill(6) for code in ensure_list(stock_codes)],
        "industry": str(item.get("industry") or ""),
        "event_type": str(item.get("event_type") or ""),
        "is_announcement": bool(item.get("is_announcement")),
        "content_level": str(item.get("content_level") or "title_only"),
        "url": str(item.get("url") or ""),
        "importance_score": item.get("importance_score"),
        "retention_level": str(item.get("retention_level") or "hot"),
    }


def _make_chunk(
    item: dict[str, Any],
    chunk_text: str,
    chunk_index: int,
    section_title: str = "",
) -> RagChunk:
    meta = _base_metadata(item)
    news_id = meta["news_id"]
    chunk_id = stable_id(news_id, chunk_index, section_title, chunk_text, prefix="chunk_")
    return RagChunk(
        chunk_id=chunk_id,
        news_id=news_id,
        chunk_index=chunk_index,
        chunk_text=clean_text(chunk_text),
        source=meta["source"],
        publish_time=meta["publish_time"],
        trade_date=meta["trade_date"],
        stock_codes=meta["stock_codes"],
        industry=meta["industry"],
        event_type=meta["event_type"],
        is_announcement=meta["is_announcement"],
        content_level=meta["content_level"],
        url=meta["url"],
        section_title=section_title,
        importance_score=meta["importance_score"],
        retention_level=meta["retention_level"],
        metadata={"title": str(item.get("title") or ""), **dict(item.get("metadata") or {})},
    )


def chunk_news(
    news: dict[str, Any],
    max_chars: int = 700,
    overlap_chars: int = 80,
) -> list[RagChunk]:
    title = clean_text(news.get("title"))
    summary = clean_text(news.get("summary"))
    content = clean_text(news.get("content"))
    parts: list[str] = []
    for part in [title, summary, content]:
        if part and part not in parts:
            parts.append(part)
    full_text = clean_text(" ".join(parts))
    if not full_text:
        return []
    if len(full_text) <= max_chars:
        return [_make_chunk(news, full_text, 0, section_title=title)]
    chunks = build_sentence_chunks(split_chinese_sentences(full_text), max_chars=max_chars, overlap_chars=overlap_chars)
    return [_make_chunk(news, text, idx, section_title=title) for idx, text in enumerate(chunks)]


def _split_announcement_sections(content: str) -> list[tuple[str, str]]:
    matches = list(ANNOUNCEMENT_HEADING_RE.finditer(content))
    if not matches:
        return [("", content)]
    sections: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        title = clean_text(match.group("title"))
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        sections.append((title, clean_text(content[start:end])))
    return sections


def chunk_announcement(
    announcement: dict[str, Any],
    max_chars: int = 700,
    overlap_chars: int = 120,
) -> list[RagChunk]:
    item = dict(announcement)
    item["is_announcement"] = True
    title = clean_text(item.get("title"))
    content = clean_text(item.get("content") or item.get("summary"))
    if not content and title:
        content = title
    chunks: list[RagChunk] = []
    for section_title, section_text in _split_announcement_sections(content):
        section_label = section_title or title
        parts = []
        for part in [title, section_label, section_text]:
            part = clean_text(part)
            if part and part not in parts:
                parts.append(part)
        body = clean_text(" ".join(parts))
        pieces = (
            [body]
            if len(body) <= max_chars
            else build_sentence_chunks(split_chinese_sentences(body), max_chars=max_chars, overlap_chars=overlap_chars)
        )
        for piece in pieces:
            chunks.append(_make_chunk(item, piece, len(chunks), section_title=section_label))
    return chunks


def chunk_decision_log(record: dict[str, Any]) -> RagChunk:
    text = clean_text(
        f"{record.get('trade_date', '')} {record.get('stock_code', '')} "
        f"{record.get('final_action', '')} {record.get('final_reason', '')}"
    )
    item = {
        "news_id": str(record.get("decision_id") or stable_id(text, prefix="decision_")),
        "title": "Agent decision log",
        "trade_date": record.get("trade_date", ""),
        "event_type": "agent_decision_log",
        "metadata": {"decision_id": record.get("decision_id", "")},
    }
    return _make_chunk(item, text, 0, section_title="agent_decision_log")


def chunk_industry_rule(record: dict[str, Any]) -> RagChunk:
    text = clean_text(
        f"{record.get('event_keyword', '')} {record.get('affected_industry', '')} "
        f"{record.get('impact_direction', '')} {record.get('description', '')}"
    )
    item = {
        "news_id": str(record.get("rule_id") or stable_id(text, prefix="industry_rule_")),
        "title": "Industry event rule",
        "industry": record.get("affected_industry", ""),
        "event_type": "industry_event_rule",
        "metadata": {"rule_id": record.get("rule_id", "")},
    }
    return _make_chunk(item, text, 0, section_title="industry_event_rule")


def chunk_agent_rule(record: dict[str, Any]) -> RagChunk:
    text = clean_text(
        f"{record.get('rule_name', '')} {record.get('rule_type', '')} "
        f"{record.get('action', '')} {record.get('description', '')} {record.get('condition', '')}"
    )
    item = {
        "news_id": str(record.get("rule_id") or stable_id(text, prefix="agent_rule_")),
        "title": "Agent rule",
        "event_type": "agent_rule",
        "metadata": {"rule_id": record.get("rule_id", "")},
    }
    return _make_chunk(item, text, 0, section_title="agent_rule")
