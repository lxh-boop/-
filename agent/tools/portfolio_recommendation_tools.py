"""Agent-only tools for portfolio recommendation use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.top_k import DEFAULT_TOOL_TOP_K
from application.use_cases.position_recommendation import (
    recommend_position_weight,
)
from application.use_cases.replacement_recommendation import (
    recommend_replacements,
)


def _context_value(
    arguments: dict[str, Any],
    context: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    value = arguments.get(key)
    if value not in (None, ""):
        return value
    value = context.get(key)
    return default if value in (None, "") else value


def _output_dir(context: dict[str, Any]) -> str | Path:
    return context.get("output_dir") or "outputs"


def _db_path(context: dict[str, Any]) -> str | Path | None:
    return context.get("db_path")


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def execute_portfolio_position_recommendation_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """Adapt Agent arguments to the target-weight recommendation use case."""

    result = recommend_position_weight(
        user_id=str(_context_value(arguments, context, "user_id", "default")),
        stock_code=str(arguments.get("stock_code") or ""),
        requested_weight=_float_or_none(arguments.get("requested_weight")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        top_k=_int_value(
            arguments.get("top_k") or context.get("default_top_k"),
            DEFAULT_TOOL_TOP_K,
        ),
    )
    payload = result.to_dict()
    data = dict(payload.get("data") or {})
    analysis = (
        dict(data.get("analysis") or {})
        if isinstance(data.get("analysis"), dict)
        else {}
    )
    stock_code = str(
        data.get("stock_code")
        or analysis.get("stock_code")
        or arguments.get("stock_code")
        or ""
    )
    recommended_weight = data.get("recommended_weight")
    data.update(
        {
            "candidate_stocks": [stock_code] if stock_code else [],
            "target_weights": (
                {stock_code: recommended_weight}
                if stock_code
                else {}
            ),
            "cash_ratio": None,
            "current_vs_target": {
                "stock_code": stock_code,
                "target_weight": recommended_weight,
                "estimated_quantity": data.get("estimated_quantity"),
            },
            "risk_notes": [
                text
                for text in [data.get("risk_warning")]
                if text
            ],
            "assumptions": [
                "Uses latest local ranking, user risk profile and current paper account state.",
                "No paper-trading write is performed by this recommendation.",
            ],
            "not_executed": True,
        }
    )
    payload["data"] = data
    payload["tool_name"] = "portfolio.recommend_position"
    return payload


def execute_portfolio_replacement_recommendation_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    """Adapt Agent arguments to the replacement-ranking use case."""

    requested_weight = _float_or_none(arguments.get("requested_weight"))
    result = recommend_replacements(
        user_id=str(_context_value(arguments, context, "user_id", "default")),
        candidate_stock_code=str(arguments.get("stock_code") or ""),
        candidate_target_weight=float(
            requested_weight if requested_weight is not None else 0.05
        ),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        limit=_int_value(arguments.get("limit"), 3),
    )
    payload = result.to_dict()
    data = dict(payload.get("data") or {})
    data.update(
        {
            "source_stock": (
                data.get("candidate_stock_code")
                or arguments.get("stock_code")
                or ""
            ),
            "score_comparison": data.get("replacement_candidates") or [],
            "risk_comparison": {
                "before": data.get("risk_before") or {},
                "after_estimate": data.get("risk_after_estimate") or {},
            },
            "not_executed": True,
        }
    )
    payload["data"] = data
    payload["tool_name"] = "portfolio.recommend_replacement"
    return payload


__all__ = [
    "execute_portfolio_position_recommendation_tool",
    "execute_portfolio_replacement_recommendation_tool",
]
