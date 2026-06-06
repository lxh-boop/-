from __future__ import annotations

import re
import hashlib


DEFAULT_RAG_QUERY = "风险 业绩 回购 减持 增持 诉讼 处罚 中标 合同 公告"


def clean_text(value) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_code(code) -> str:
    return str(code or "").strip().split(".")[0].zfill(6)


def normalize_query(query: str | None) -> str:
    query = clean_text(query)
    return query if query else DEFAULT_RAG_QUERY


def make_doc_id(code: str, date, title: str, source: str) -> str:
    raw = f"{normalize_code(code)}|{clean_text(date)}|{clean_text(title)}|{clean_text(source)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()
