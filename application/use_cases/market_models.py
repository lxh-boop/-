"""Business result models for market and portfolio analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class StockAnalysis:
    stock_code: str
    stock_name: str = ""
    trade_date: str = ""
    current_price: float = 0.0
    original_score: float = 0.0
    original_rank: int | None = None
    model_confidence: str | float = ""
    news_adjustment: float = 0.0
    effective_news_adjustment: float = 0.0
    user_adjustment: float = 0.0
    combined_adjustment: float = 0.0
    target_weight: float = 0.0
    current_weight: float = 0.0
    position_adjustment_ratio: float = 0.0
    ai_reliability_weight: float = 0.0
    news_summary: str = "No valid news evidence was found."
    announcement_summary: str = ""
    positive_evidence: list[str] = field(default_factory=list)
    negative_evidence: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    triggered_rules: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    suitability_for_user: str = "unknown"
    analysis_conclusion: str = ""
    non_topk_warning: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PositionRecommendation:
    user_id: str
    stock_code: str
    trade_date: str
    minimum_weight: float = 0.0
    recommended_weight: float = 0.0
    maximum_allowed_weight: float = 0.0
    recommended_amount: float = 0.0
    estimated_quantity: float = 0.0
    lot_size: int = 100
    estimated_cost: float = 0.0
    confidence: str = "medium"
    reason: str = ""
    risk_warning: str = ""
    hard_rejection: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReplacementCandidate:
    stock_code: str
    stock_name: str = ""
    current_weight: float = 0.0
    recommended_weight_after: float = 0.0
    reduce_weight: float = 0.0
    estimated_sell_quantity: float = 0.0
    replacement_priority_score: float = 0.0
    replacement_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReplacementRecommendation:
    user_id: str
    candidate_stock_code: str
    candidate_target_weight: float
    trade_date: str
    replacement_candidates: list[ReplacementCandidate] = field(
        default_factory=list
    )
    risk_before: dict = field(default_factory=dict)
    risk_after_estimate: dict = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["replacement_candidates"] = [
            item.to_dict() for item in self.replacement_candidates
        ]
        return data


__all__ = [
    "PositionRecommendation",
    "ReplacementCandidate",
    "ReplacementRecommendation",
    "StockAnalysis",
]
