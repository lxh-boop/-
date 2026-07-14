from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


COMPLIANCE_DISCLAIMER = (
    "本项目仅用于机器学习研究、金融数据分析、量化策略验证、模拟盘展示和项目作品集展示。"
    "不构成投资建议，不承诺收益，不用于实盘自动交易。"
)

CORE_QUESTIONS = (
    "用户是否适合",
    "模型预测是否可靠",
    "新闻事件是否带来风险",
    "Agent 修改是否有效",
)

ALLOWED_ACTIONS = (
    "retain",
    "down_weight",
    "exclude",
    "watch",
    "risk_warning",
    "explain_only",
    "no_action",
)

ACTION_DISPLAY_NAMES = {
    "retain": "保留",
    "down_weight": "降权",
    "exclude": "剔除",
    "watch": "加入观察",
    "risk_warning": "风险提示",
    "explain_only": "仅解释",
    "no_action": "不调整",
}


def validate_action(action: str) -> str:
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unsupported action: {action}")
    return action


def clamp_score(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, float(value)))


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_id: str
    evidence_type: str
    source_id: str
    text: str
    trade_date: str | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class UserSuitabilityContext:
    user_id: str
    risk_level: str
    investment_horizon: str | None = None
    liquidity_need: str | None = None
    max_drawdown_tolerance: float | None = None
    volatility_tolerance: str | None = None
    current_positions: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelPredictionContext:
    trade_date: str
    stock_code: str
    stock_name: str
    model_name: str
    pred_score: float
    pred_rank: int | None = None
    pred_return: float | None = None
    risk_score: float | None = None
    confidence: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NewsRiskContext:
    news_id: str
    trade_date: str
    event_type: str
    sentiment: str
    impact_direction: str
    impact_strength: float
    mapping_confidence: float
    evidence_text: str
    stock_code: str | None = None
    industry: str | None = None
    is_major_event: bool = False


@dataclass(frozen=True)
class AgentEffectivenessContext:
    decision_id: str
    trade_date: str
    stock_code: str
    original_pred_score: float
    final_action: str
    final_score: float
    future_return_1d: float | None = None
    future_return_5d: float | None = None
    is_effective: bool | None = None


@dataclass(frozen=True)
class SkillRequest:
    skill_name: str
    trade_date: str
    user: UserSuitabilityContext | None = None
    prediction: ModelPredictionContext | None = None
    news_events: list[NewsRiskContext] = field(default_factory=list)
    evidence: list[EvidenceSnapshot] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillResult:
    skill_name: str
    action: str = "no_action"
    score_adjustment: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    risk_warning: str = COMPLIANCE_DISCLAIMER
    triggered_rules: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        validate_action(self.action)
        data = asdict(self)
        data["score_adjustment"] = clamp_score(data["score_adjustment"])
        data["confidence"] = max(0.0, min(1.0, float(data["confidence"])))
        return data
