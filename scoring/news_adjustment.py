from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from scoring.normalizers import clamp, safe_float
from scoring.schemas import NewsEvidenceSignal


@dataclass(frozen=True)
class NewsAdjustmentResult:
    news_adjustment_score: float = 0.0
    news_adjustment_direction: str = "neutral"
    evidence_news_ids: list[str] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    reason: str = "No usable news evidence."
    major_negative: bool = False


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"]:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _usable_for_trade_date(evidence: NewsEvidenceSignal, fallback_trade_date: str = "") -> bool:
    evidence_trade_dt = _parse_datetime(evidence.trade_date)
    fallback_trade_dt = _parse_datetime(fallback_trade_date)
    if evidence_trade_dt and fallback_trade_dt and evidence_trade_dt.date() > fallback_trade_dt.date():
        return False

    trade_date = fallback_trade_date or evidence.trade_date
    publish_dt = _parse_datetime(evidence.publish_time)
    trade_dt = _parse_datetime(trade_date)
    if not publish_dt or not trade_dt:
        return True
    if publish_dt.date() > trade_dt.date():
        return False
    if publish_dt.date() == trade_dt.date() and publish_dt.time() >= time(15, 0):
        return False
    return True


def _direction_weight(direction: str) -> float:
    text = str(direction or "").lower()
    if text in {"positive", "bullish", "good", "benefit"}:
        return 1.0
    if text in {"negative", "bearish", "bad", "risk"}:
        return -1.0
    return 0.0


def calculate_news_adjustment(
    evidence: list[NewsEvidenceSignal | dict[str, Any]] | NewsEvidenceSignal | dict[str, Any] | None,
    trade_date: str = "",
) -> NewsAdjustmentResult:
    if evidence is None:
        return NewsAdjustmentResult()
    items = evidence if isinstance(evidence, list) else [evidence]
    signals = [
        item if isinstance(item, NewsEvidenceSignal) else NewsEvidenceSignal.from_mapping(item)
        for item in items
    ]

    total = 0.0
    news_ids: list[str] = []
    chunk_ids: list[str] = []
    directions: list[str] = []
    reasons: list[str] = []
    major_negative = False

    for item in signals:
        if not _usable_for_trade_date(item, trade_date):
            reasons.append(f"{item.news_id or 'news'} ignored because it is after the decision cutoff.")
            continue

        direction_weight = _direction_weight(item.impact_direction)
        if direction_weight == 0.0:
            continue

        impact_confidence = clamp(item.impact_confidence, 0.0, 1.0)
        mapping_confidence = clamp(item.mapping_confidence, 0.0, 1.0)
        if impact_confidence < 0.40 or mapping_confidence < 0.40:
            reasons.append(f"{item.news_id or 'news'} ignored because confidence is low.")
            continue

        strength = clamp(item.impact_strength, 0.0, 1.0)
        importance = clamp(item.importance_score, 0.0, 1.0)
        raw = 0.30 * direction_weight * strength * impact_confidence * mapping_confidence * max(0.50, importance)
        total += raw
        if item.news_id:
            news_ids.append(item.news_id)
        chunk_ids.extend(item.evidence_chunk_ids)
        directions.append("positive" if direction_weight > 0 else "negative")
        if item.reason or item.evidence_text:
            reasons.append(item.reason or item.evidence_text[:120])
        if direction_weight < 0 and mapping_confidence >= 0.80 and impact_confidence >= 0.70 and strength >= 0.70:
            major_negative = True

    score = clamp(total, -0.30, 0.30)
    if score > 0:
        direction = "positive"
    elif score < 0:
        direction = "negative"
    else:
        direction = "neutral"
    reason = "; ".join(reasons) if reasons else ("News evidence supports adjustment." if score else "No usable news evidence.")
    return NewsAdjustmentResult(
        news_adjustment_score=score,
        news_adjustment_direction=direction,
        evidence_news_ids=sorted(set(news_ids)),
        evidence_chunk_ids=sorted(set(chunk_ids)),
        reason=reason,
        major_negative=major_negative,
    )
