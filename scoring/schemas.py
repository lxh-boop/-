from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


COMPLIANCE_DISCLAIMER = (
    "This output is for machine-learning research, financial data analysis, "
    "paper-trading validation, and project demonstration only. It is not "
    "investment advice and must not be used as a real trading instruction."
)


def now_text() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _stock_code(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text.split(".")[0].zfill(6)


@dataclass(frozen=True)
class ModelPredictionSignal:
    trade_date: str
    stock_code: str
    pred_score: float
    pred_rank: int | None = None
    confidence: str | float = "medium"
    stock_name: str = ""
    industry: str = ""
    model_name: str = ""
    pred_return: float | None = None
    current_price: float | None = None
    risk_level: str = "medium"
    total_count: int | None = None

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "ModelPredictionSignal":
        return cls(
            trade_date=str(data.get("trade_date") or data.get("prediction_date") or data.get("date") or ""),
            stock_code=_stock_code(data.get("stock_code") or data.get("code")),
            stock_name=str(data.get("stock_name") or data.get("name") or ""),
            industry=str(data.get("industry") or data.get("stock_industry") or ""),
            pred_score=float(data.get("pred_score") if data.get("pred_score") is not None else data.get("score", 0.0)),
            pred_rank=(int(data["pred_rank"]) if data.get("pred_rank") not in [None, ""] else int(data["rank"]) if data.get("rank") not in [None, ""] else None),
            confidence=data.get("confidence", "medium"),
            model_name=str(data.get("model_name") or ""),
            pred_return=(float(data["pred_return"]) if data.get("pred_return") not in [None, ""] else float(data["pred_5d_ret"]) if data.get("pred_5d_ret") not in [None, ""] else None),
            current_price=(
                float(data["current_price"])
                if data.get("current_price") not in [None, ""]
                else float(data["close"])
                if data.get("close") not in [None, ""]
                else float(data["price"])
                if data.get("price") not in [None, ""]
                else None
            ),
            risk_level=str(data.get("risk_level") or "medium"),
            total_count=(int(data["total_count"]) if data.get("total_count") not in [None, ""] else None),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stock_code"] = _stock_code(self.stock_code)
        return data


@dataclass(frozen=True)
class NewsEvidenceSignal:
    news_id: str = ""
    impact_direction: str = "neutral"
    impact_strength: float = 0.0
    impact_confidence: float = 0.0
    mapping_confidence: float = 0.0
    importance_score: float = 1.0
    evidence_chunk_ids: list[str] = field(default_factory=list)
    publish_time: str = ""
    trade_date: str = ""
    stock_code: str = ""
    reason: str = ""
    evidence_text: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "NewsEvidenceSignal":
        chunks = data.get("evidence_chunk_ids")
        if chunks is None:
            chunks = data.get("chunk_ids") or data.get("chunk_id") or []
        if isinstance(chunks, str):
            chunks = [chunks] if chunks else []
        return cls(
            news_id=str(data.get("news_id") or ""),
            stock_code=_stock_code(data.get("stock_code") or data.get("code")),
            impact_direction=str(data.get("impact_direction") or "neutral"),
            impact_strength=float(data.get("impact_strength") or data.get("relevance_score") or 0.0),
            impact_confidence=float(data.get("impact_confidence") or 0.0),
            mapping_confidence=float(data.get("mapping_confidence") or 0.0),
            importance_score=float(data.get("importance_score") if data.get("importance_score") not in [None, ""] else 1.0),
            evidence_chunk_ids=[str(item) for item in chunks],
            publish_time=str(data.get("publish_time") or ""),
            trade_date=str(data.get("trade_date") or ""),
            reason=str(data.get("reason") or data.get("evidence_text") or ""),
            evidence_text=str(data.get("evidence_text") or data.get("chunk_text") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class UserConstraintSignal:
    user_id: str = "default_user"
    profile_type: str = "balanced"
    risk_level: str = "C3"
    max_drawdown_tolerance: float = 0.15
    liquidity_need: str = "medium"
    investment_horizon: str = "medium"
    investment_goal: str = "balanced_growth"
    allow_high_volatility: bool = False
    preferred_industries: list[str] = field(default_factory=list)
    avoided_industries: list[str] = field(default_factory=list)
    max_single_position: float = 0.08
    max_industry_position: float = 0.30

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "UserConstraintSignal":
        data = data or {}
        return cls(
            user_id=str(data.get("user_id") or "default_user"),
            profile_type=str(data.get("profile_type") or "balanced"),
            risk_level=str(data.get("risk_level") or "C3"),
            max_drawdown_tolerance=float(data.get("max_drawdown_tolerance") or 0.15),
            liquidity_need=str(data.get("liquidity_need") or "medium"),
            investment_horizon=str(data.get("investment_horizon") or data.get("target_period") or "medium"),
            investment_goal=str(data.get("investment_goal") or data.get("goal_type") or "balanced_growth"),
            allow_high_volatility=bool(data.get("allow_high_volatility", False)),
            preferred_industries=list(data.get("preferred_industries") or []),
            avoided_industries=list(data.get("avoided_industries") or []),
            max_single_position=float(data.get("max_single_position") or 0.08),
            max_industry_position=float(data.get("max_industry_position") or 0.30),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioConstraintSignal:
    current_position_ratio: float = 0.0
    industry_position_ratio: float = 0.0
    max_single_position: float = 0.08
    max_industry_position: float = 0.30
    portfolio_risk_level: str = "low"
    stock_risk_level: str = "medium"
    volatility: float = 0.0
    drawdown: float = 0.0
    confidence: str | float = "medium"
    stock_industry: str = ""

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "PortfolioConstraintSignal":
        data = data or {}
        return cls(
            current_position_ratio=float(data.get("current_position_ratio") or data.get("position_ratio") or 0.0),
            industry_position_ratio=float(data.get("industry_position_ratio") or data.get("industry_ratio") or 0.0),
            max_single_position=float(data.get("max_single_position") or 0.08),
            max_industry_position=float(data.get("max_industry_position") or 0.30),
            portfolio_risk_level=str(data.get("portfolio_risk_level") or data.get("risk_level") or "low"),
            stock_risk_level=str(data.get("stock_risk_level") or data.get("stock_risk") or "medium"),
            volatility=float(data.get("volatility") or data.get("vol_20") or 0.0),
            drawdown=float(data.get("drawdown") or data.get("max_drawdown") or 0.0),
            confidence=data.get("confidence", "medium"),
            stock_industry=str(data.get("stock_industry") or data.get("industry") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRuleSignal:
    rule_id: str
    rule_name: str = ""
    rule_type: str = ""
    condition: dict[str, Any] = field(default_factory=dict)
    action: str = ""
    priority: int = 100
    is_active: bool = True

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AgentRuleSignal":
        return cls(
            rule_id=str(data.get("rule_id") or data.get("id") or ""),
            rule_name=str(data.get("rule_name") or data.get("name") or ""),
            rule_type=str(data.get("rule_type") or ""),
            condition=dict(data.get("condition") or {}),
            action=str(data.get("action") or ""),
            priority=int(data.get("priority") or 100),
            is_active=bool(data.get("is_active", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TriggeredRule:
    rule_id: str
    rule_name: str
    reason: str
    penalty_score: float = 0.0
    forced_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreBreakdown:
    model_score_norm: float = 0.0
    news_adjustment: float = 0.0
    user_adjustment: float = 0.0
    effective_news_adjustment: float = 0.0
    combined_adjustment: float = 0.0
    confidence_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FusionInput:
    model_prediction: ModelPredictionSignal
    news_evidence: list[NewsEvidenceSignal] = field(default_factory=list)
    user_constraints: UserConstraintSignal | None = None
    portfolio_constraints: PortfolioConstraintSignal | None = None
    agent_rules: list[AgentRuleSignal] = field(default_factory=list)
    rag_evidence: list[dict[str, Any]] = field(default_factory=list)
    ai_reliability_weight: float = 0.00


@dataclass(frozen=True)
class FusionOutput:
    user_id: str
    trade_date: str
    stock_code: str
    original_pred_score: float
    original_pred_rank: int | None
    original_score: float = 0.0
    original_rank: int | None = None
    news_adjustment: float = 0.0
    user_adjustment: float = 0.0
    effective_news_adjustment: float = 0.0
    combined_adjustment: float = 0.0
    original_target_weight: float = 0.0
    target_weight: float = 0.0
    position_adjustment_ratio: float = 1.0
    adjustment_reason: str = ""
    ai_adjustment_confidence: float = 0.0
    ai_reliability_weight: float = 0.00
    current_price: float | None = None
    ai_adjustment_effect_status: str = "pending"
    ai_adjustment_score: float | None = None
    confidence: str = "medium"
    triggered_rules: list[TriggeredRule] = field(default_factory=list)
    evidence_news_ids: list[str] = field(default_factory=list)
    evidence_chunk_ids: list[str] = field(default_factory=list)
    reason: str = ""
    risk_warning: str = ""
    compliance_disclaimer: str = COMPLIANCE_DISCLAIMER
    score_breakdown: ScoreBreakdown = field(default_factory=ScoreBreakdown)
    created_at: str = field(default_factory=now_text)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["triggered_rules"] = [rule.to_dict() for rule in self.triggered_rules]
        data["score_breakdown"] = self.score_breakdown.to_dict()
        for forbidden in [
            "final_action",
            "risk_penalty",
            "rule_penalty",
            "risk_penalty_score",
            "rule_penalty_score",
            "risk_score_penalty",
            "rule_score_penalty",
        ]:
            data.pop(forbidden, None)
        return data


@dataclass(frozen=True)
class FinalRecommendationRecord:
    output: FusionOutput
    stock_name: str = ""
    model_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = self.output.to_dict()
        data["stock_name"] = self.stock_name
        data["model_name"] = self.model_name
        data["rank"] = self.output.original_pred_rank
        data["date"] = self.output.trade_date
        data["code"] = self.output.stock_code
        data["score"] = self.output.original_pred_score
        return data
