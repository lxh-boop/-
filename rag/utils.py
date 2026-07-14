from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any


DEFAULT_EVENT_TERMS = [
    "减持",
    "回购",
    "处罚",
    "业绩预告",
    "重大合同",
    "锂价下跌",
    "销量不及预期",
    "监管",
    "诉讼",
    "风险提示",
    "事故",
    "下修",
    "亏损",
]


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def stable_id(*parts: Any, prefix: str = "") -> str:
    raw = "|".join(clean_text(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}{digest}" if prefix else digest


def ensure_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d %H:%M:%S",
        "%Y%m%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%d",
    ]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def normalize_date_text(value: Any) -> str:
    dt = parse_datetime(value)
    return dt.strftime("%Y-%m-%d") if dt else clean_text(value)


def normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    min_v = min(values)
    max_v = max(values)
    if abs(max_v - min_v) < 1e-12:
        return [1.0 if value > 0 else 0.0 for value in values]
    return [(value - min_v) / (max_v - min_v) for value in values]
