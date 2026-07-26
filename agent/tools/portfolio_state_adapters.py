"""Agent-only portfolio-state tools backed by the portfolio service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.services.portfolio_service import portfolio_service


def _context_value(args: dict[str, Any], context: dict[str, Any], key: str, default: Any = None) -> Any:
    value = args.get(key)
    if value not in (None, ""):
        return value
    value = context.get(key)
    return default if value in (None, "") else value


def _output_dir(context: dict[str, Any]) -> str | Path:
    return context.get("output_dir") or "outputs"


def _db_path(context: dict[str, Any]) -> str | Path | None:
    return context.get("db_path")


def execute_portfolio_state_query_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    data = portfolio_service.get_portfolio_state(
        str(_context_value(args, context, "user_id", "default")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
    )
    return {
        "success": True,
        "message": "Portfolio state queried.",
        "data": data,
        "warnings": [],
        "errors": [],
        "tool_name": "portfolio.get_state",
    }


def execute_portfolio_account_summary_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    data = portfolio_service.get_account_summary(
        str(_context_value(args, context, "user_id", "default")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
    )
    return {
        "success": bool(data.get("account")),
        "message": "Account summary queried." if data.get("account") else "Account summary is empty.",
        "data": data,
        "warnings": [] if data.get("account") else ["missing_account"],
        "errors": [],
        "tool_name": "portfolio.get_account_summary",
    }


def execute_portfolio_positions_query_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    data = portfolio_service.get_current_positions(
        str(_context_value(args, context, "user_id", "default")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
    )
    return {
        "success": True,
        "message": "Positions queried.",
        "data": data,
        "warnings": [],
        "errors": [],
        "tool_name": "portfolio.get_positions",
    }


def execute_portfolio_orders_query_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    data = portfolio_service.get_current_orders(
        str(_context_value(args, context, "user_id", "default")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
    )
    return {
        "success": True,
        "message": "Orders queried.",
        "data": data,
        "warnings": [],
        "errors": [],
        "tool_name": "portfolio.get_orders",
    }


__all__ = [
    "execute_portfolio_account_summary_tool",
    "execute_portfolio_orders_query_tool",
    "execute_portfolio_positions_query_tool",
    "execute_portfolio_state_query_tool",
]
