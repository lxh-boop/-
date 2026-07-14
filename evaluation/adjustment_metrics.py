from __future__ import annotations

from typing import Any


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in [None, ""]:
            return default
        return float(value)
    except Exception:
        return default


def _normalized_signed_return(value: float, scale: float = 0.05) -> float:
    return clamp(0.5 + safe_float(value) / max(scale, 1e-9) / 2.0)


def _normalized_non_negative(value: float, scale: float = 0.01) -> float:
    return clamp(safe_float(value) / max(scale, 1e-9))


def calculate_adjustment_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Evaluate whether an AI position adjustment improved the original decision."""

    original_weight = safe_float(record.get("original_target_weight"), 0.0)
    ai_weight = safe_float(record.get("target_weight"), 0.0)
    future_return = safe_float(record.get("future_return_5d"), 0.0)
    future_excess_return = safe_float(record.get("future_excess_return_5d"), future_return)
    risk_reduction_effect = safe_float(record.get("risk_reduction_effect"), 0.0)

    original_decision_return = original_weight * future_excess_return
    ai_adjusted_decision_return = ai_weight * future_excess_return
    adjustment_alpha = ai_adjusted_decision_return - original_decision_return

    reduced_weight = ai_weight < original_weight - 1e-9
    kept_or_increased = ai_weight >= original_weight * 0.95
    if reduced_weight:
        adjustment_hit = 1 if future_excess_return <= 0 else 0
    elif kept_or_increased:
        adjustment_hit = 1 if future_excess_return >= 0 else 0
    else:
        adjustment_hit = 1 if adjustment_alpha >= 0 else 0

    avoided_loss = max(0.0, original_weight - ai_weight) * max(0.0, -future_excess_return)
    missed_gain = max(0.0, original_weight - ai_weight) * max(0.0, future_excess_return)
    false_down_weight = int(reduced_weight and future_excess_return >= 0.03)
    false_keep = int(kept_or_increased and future_excess_return <= -0.03)

    avoided_scale = max(original_weight * 0.05, 0.001)
    missed_scale = max(original_weight * 0.05, 0.001)
    ai_adjustment_score = clamp(
        0.35 * adjustment_hit
        + 0.25 * _normalized_signed_return(adjustment_alpha)
        + 0.20 * _normalized_non_negative(avoided_loss, avoided_scale)
        - 0.15 * _normalized_non_negative(missed_gain, missed_scale)
        + 0.05 * clamp(risk_reduction_effect, 0.0, 1.0)
    )

    return {
        "original_decision_return": original_decision_return,
        "ai_adjusted_decision_return": ai_adjusted_decision_return,
        "adjustment_hit": adjustment_hit,
        "avoided_loss": avoided_loss,
        "missed_gain": missed_gain,
        "adjustment_alpha": adjustment_alpha,
        "false_down_weight": false_down_weight,
        "false_keep": false_keep,
        "risk_reduction_effect": risk_reduction_effect,
        "ai_adjustment_score": ai_adjustment_score,
    }
