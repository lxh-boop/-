from dataclasses import dataclass
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, str) and (value.strip() == "" or value.strip().lower() in {"nan", "null", "none", "na"}):
        return float(default)
    try:
        result = float(value)
        if result != result:
            return float(default)
        return result
    except (TypeError, ValueError):
        return float(default)


def clamp(value: Any, min_value: float = 0.0, max_value: float = 1.0) -> float:
    low = float(min_value)
    high = float(max_value)
    if high < low:
        low, high = high, low
    number = safe_float(value, low)
    return max(low, min(high, number))


def safe_float_with_log(value: Any, default: float = 0.0, field_name: str = "", warnings: list[str] | None = None) -> float:
    if value is None:
        if field_name and warnings is not None:
            warnings.append(f"{field_name} was None; using default={default}")
        return float(default)
    if isinstance(value, str) and value.strip() == "":
        if field_name and warnings is not None:
            warnings.append(f"{field_name} was empty string; using default={default}")
        return float(default)
    try:
        result = float(value)
        if result != result:
            if field_name and warnings is not None:
                warnings.append(f"{field_name} was NaN; using default={default}")
            return float(default)
        return result
    except (TypeError, ValueError):
        if field_name and warnings is not None:
            warnings.append(f"{field_name}={value!r} cannot be converted to float; using default={default}")
        return float(default)


@dataclass(frozen=True)
class PositionAdjustmentResult:
    news_adjustment: float = 0.0
    user_adjustment: float = 0.0
    ai_reliability_weight: float = 1.0
    effective_news_adjustment: float = 0.0
    combined_adjustment: float = 0.0
    position_adjustment_ratio: float = 1.0
    adjustment_formula_version: str = "v3_base_weight_times_adjustment_ratio_null_safe"

    def to_dict(self) -> dict[str, Any]:
        return {
            "news_adjustment": self.news_adjustment,
            "user_adjustment": self.user_adjustment,
            "ai_reliability_weight": self.ai_reliability_weight,
            "effective_news_adjustment": self.effective_news_adjustment,
            "combined_adjustment": self.combined_adjustment,
            "position_adjustment_ratio": self.position_adjustment_ratio,
            "adjustment_formula_version": self.adjustment_formula_version,
        }


def calculate_position_adjustment(
    news_adjustment: Any = None,
    user_adjustment: Any = None,
    ai_reliability_weight: Any = None,
) -> PositionAdjustmentResult:
    news = safe_float(news_adjustment, default=0.0)
    user = safe_float(user_adjustment, default=0.0)
    reliability = safe_float(ai_reliability_weight, default=1.0)
    reliability = clamp(reliability, 0.0, 1.0)
    effective_news = reliability * news
    combined = clamp(effective_news + user, -1.0, 1.0)
    ratio = clamp(1.0 + combined, 0.0, 2.0)
    return PositionAdjustmentResult(
        news_adjustment=news,
        user_adjustment=user,
        ai_reliability_weight=reliability,
        effective_news_adjustment=effective_news,
        combined_adjustment=combined,
        position_adjustment_ratio=ratio,
    )


def normalize_score(value: Any, min_value: float = 0.0, max_value: float = 1.0) -> float:
    number = safe_float(value, 0.0)
    low = float(min_value)
    high = float(max_value)
    if high == low:
        return 0.0
    if high < low:
        low, high = high, low
    return clamp((number - low) / (high - low), 0.0, 1.0)


def normalize_rank(rank: Any, total_count: Any) -> float:
    total = int(safe_float(total_count, 0.0))
    if total <= 1:
        return 0.5
    rank_value = int(safe_float(rank, total))
    rank_value = max(1, min(total, rank_value))
    return clamp(1.0 - (rank_value - 1) / (total - 1), 0.0, 1.0)


def normalize_confidence(confidence: Any) -> float:
    if isinstance(confidence, (int, float)):
        return clamp(float(confidence), 0.0, 1.0)
    text = str(confidence or "").strip().lower()
    mapping = {
        "very_low": 0.1,
        "low": 0.2,
        "medium": 0.55,
        "mid": 0.55,
        "normal": 0.55,
        "high": 0.85,
        "very_high": 0.95,
    }
    return mapping.get(text, 0.55)
