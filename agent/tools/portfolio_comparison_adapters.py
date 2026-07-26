"""Agent-only adapters for portfolio comparison application use cases."""

from __future__ import annotations

from typing import Any

from application.use_cases.portfolio_comparison import (
    compare_portfolios,
    construct_target_portfolio,
    design_target_portfolio,
    load_target_portfolio,
)


def execute_design_target_portfolio_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return design_target_portfolio(arguments, context)


def execute_construct_target_portfolio_tool(
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    return construct_target_portfolio(arguments, context)


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
    "execute_compare_portfolios_tool",
    "execute_construct_target_portfolio_tool",
    "execute_design_target_portfolio_tool",
    "execute_load_target_portfolio_tool",
]
