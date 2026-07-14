from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


_DATE_PATTERNS = (
    "%Y-%m-%d",
    "%Y%m%d",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)


def normalize_trade_date(value: Any) -> date:
    """Normalize business dates used by replay, audit, account, and order files."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        raise ValueError("empty trade_date")
    if text.startswith("Timestamp("):
        match = re.search(r"['\"]([^'\"]+)['\"]", text)
        if match:
            text = match.group(1)
    candidates = []
    if len(text) >= 19:
        candidates.append(text[:19])
    if len(text) >= 16:
        candidates.append(text[:16])
    if len(text) >= 10:
        candidates.append(text[:10])
    compact = re.sub(r"[^0-9]", "", text)
    if len(compact) >= 8:
        candidates.append(compact[:8])
    candidates.append(text)
    for candidate in dict.fromkeys(candidates):
        for pattern in _DATE_PATTERNS:
            try:
                return datetime.strptime(candidate, pattern).date()
            except ValueError:
                continue
    raise ValueError(f"invalid trade_date: {value!r}")


def normalize_trade_date_text(value: Any) -> str:
    return normalize_trade_date(value).strftime("%Y-%m-%d")


def trade_date_token(value: Any) -> str:
    return normalize_trade_date(value).strftime("%Y%m%d")


def normalize_stock_code(value: Any) -> str:
    """Normalize project-internal A-share codes to six digits.

    The current project stores paper positions, orders, rankings, and AI
    adjustments as six-digit codes. Exchange suffixes and prefixes are stripped
    before matching so 000001.SZ, SZ000001, and 000001 align.
    """

    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE"}:
        return ""
    prefix_match = re.fullmatch(r"(SH|SZ|BJ)(\d{6})", text)
    if prefix_match:
        return prefix_match.group(2)
    suffix_match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", text)
    if suffix_match:
        return suffix_match.group(1)
    digit_match = re.search(r"(\d{6})", text)
    if digit_match:
        return digit_match.group(1)
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return ""
