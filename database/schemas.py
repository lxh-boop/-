from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


COMPLIANCE_DISCLAIMER = (
    "本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目作品集展示。"
    "不构成投资建议。不承诺收益。不用于实盘自动交易。"
)


def utc_now_text() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def json_dumps(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: Any, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class MappingConfidenceInputs:
    entity_score: float = 0.0
    event_score: float = 0.0
    industry_score: float = 0.0
    source_score: float = 0.0
    position_score: float = 0.0
    llm_score: float = 0.0
    penalty: float = 0.0


def calculate_mapping_confidence(
    entity_score: float = 0.0,
    event_score: float = 0.0,
    industry_score: float = 0.0,
    source_score: float = 0.0,
    position_score: float = 0.0,
    llm_score: float = 0.0,
    penalty: float = 0.0,
    clamp: bool = True,
) -> float:
    """Calculate news-stock mapping confidence using the database design formula."""

    score = (
        0.35 * float(entity_score)
        + 0.20 * float(event_score)
        + 0.15 * float(industry_score)
        + 0.10 * float(source_score)
        + 0.10 * float(position_score)
        + 0.10 * float(llm_score)
        - float(penalty)
    )
    return clamp01(score) if clamp else float(score)


@dataclass(frozen=True)
class AgentDecisionLogRecord:
    decision_id: str
    user_id: str
    trade_date: str
    stock_code: str
    original_pred_score: float
    original_pred_rank: int | None = None
    news_adjustment: str = ""
    risk_adjustment: str = ""
    user_constraint: dict[str, Any] = field(default_factory=dict)
    triggered_rules: list[str] = field(default_factory=list)
    combined_adjustment: float = 0.0
    position_adjustment_ratio: float = 1.0
    final_reason: str = ""
    evidence_news_ids: list[str] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    evidence_snapshot: list[dict[str, Any]] = field(default_factory=list)
    retrieval_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in [
            "user_constraint",
            "triggered_rules",
            "evidence_news_ids",
            "evidence_chunk_ids",
            "evidence_snapshot",
        ]:
            data[key] = json_dumps(data[key])
        return data


@dataclass(frozen=True)
class NewsStockMappingRecord:
    mapping_id: str
    news_id: str
    stock_code: str
    stock_name: str = ""
    industry: str = ""
    concept: str = ""
    relevance_score: float = 0.0
    impact_direction: str = "neutral"
    impact_strength: float = 0.0
    impact_confidence: float = 0.0
    mapping_confidence: float = 0.0
    mapping_method: str = ""
    evidence_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
