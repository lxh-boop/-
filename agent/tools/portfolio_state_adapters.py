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


def execute_portfolio_snapshot_read_tool(
    args: dict[str, Any],
    context: dict[str, Any],
) -> Any:
    data = portfolio_service.read_portfolio_snapshot(
        str(_context_value(args, context, "user_id", "default")),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
    )
    return {
        "success": bool(data.get("success")),
        "message": str(data.get("message") or "Portfolio snapshot read."),
        "data": data,
        "warnings": list(data.get("consistency_warnings") or []),
        "errors": list(data.get("consistency_errors") or []),
        "tool_name": "portfolio.read_snapshot",
    }


def execute_portfolio_orders_list_tool(
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
        "tool_name": "portfolio.list_orders",
    }


__all__ = [
    "execute_portfolio_orders_list_tool",
    "execute_portfolio_snapshot_read_tool",
]
