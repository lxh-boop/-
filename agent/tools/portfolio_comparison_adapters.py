"""Agent-only adapters for portfolio comparison application use cases."""

from __future__ import annotations

from typing import Any

from application.use_cases.portfolio_comparison import (
    calculate_target_portfolio,
    compare_portfolios,
    load_target_portfolio,
    save_target_portfolio_artifact,
)


def execute_calculate_target_portfolio_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return calculate_target_portfolio(arguments, context)


def execute_save_target_portfolio_artifact_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return save_target_portfolio_artifact(arguments, context)


def execute_load_target_portfolio_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return load_target_portfolio(arguments, context)


def execute_compare_portfolios_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return compare_portfolios(arguments, context)


__all__ = [
    "execute_calculate_target_portfolio_tool",
    "execute_compare_portfolios_tool",
    "execute_load_target_portfolio_tool",
    "execute_save_target_portfolio_artifact_tool",
]
