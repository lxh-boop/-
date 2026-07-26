"""Agent-only tools for read-only strategy workflow queries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from application.use_cases.strategy_queries import (
    read_active_strategy_proposal,
    read_strategy_audit_trace,
    read_strategy_context,
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


def _resolve_call(
    arguments: dict[str, Any] | None,
    context: dict[str, Any] | None,
    legacy: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_arguments = dict(arguments or {})
    resolved_arguments.update(
        {
            key: value
            for key, value in legacy.items()
            if value not in (None, "")
        }
    )
    return resolved_arguments, dict(context or {})


def _tool_payload(result: Any, tool_name: str) -> dict[str, Any]:
    payload = result.to_dict()
    payload["tool_name"] = tool_name
    return payload


def execute_strategy_context_tool(
    arguments: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    *,
    user_id: str = "",
    account_id: str = "",
    conversation_id: str = "",
    output_dir: str | Path = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt Agent or legacy registry arguments to the context use case."""

    args, ctx = _resolve_call(
        arguments,
        context,
        {
            "user_id": user_id,
            "account_id": account_id,
            "conversation_id": conversation_id,
            "output_dir": output_dir,
            "db_path": db_path,
        },
    )
    scoped_user = str(_context_value(args, ctx, "user_id", "default"))
    return _tool_payload(
        read_strategy_context(
            user_id=scoped_user,
            account_id=str(
                _context_value(args, ctx, "account_id", f"paper_{scoped_user}")
            ),
            conversation_id=str(
                _context_value(
                    args,
                    ctx,
                    "conversation_id",
                    ctx.get("session_id") or "",
                )
            ),
            output_dir=args.get("output_dir") or ctx.get("output_dir") or "outputs",
            db_path=args.get("db_path") or ctx.get("db_path"),
        ),
        "strategy.get_context",
    )


def execute_active_strategy_proposal_tool(
    arguments: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    *,
    user_id: str = "",
    account_id: str = "",
    conversation_id: str = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt Agent or legacy arguments to the active-proposal use case."""

    args, ctx = _resolve_call(
        arguments,
        context,
        {
            "user_id": user_id,
            "account_id": account_id,
            "conversation_id": conversation_id,
            "db_path": db_path,
        },
    )
    scoped_user = str(_context_value(args, ctx, "user_id", "default"))
    return _tool_payload(
        read_active_strategy_proposal(
            user_id=scoped_user,
            account_id=str(
                _context_value(args, ctx, "account_id", f"paper_{scoped_user}")
            ),
            conversation_id=str(
                _context_value(
                    args,
                    ctx,
                    "conversation_id",
                    ctx.get("session_id") or "",
                )
            ),
            db_path=args.get("db_path") or ctx.get("db_path"),
        ),
        "strategy.get_active_proposal",
    )


def execute_strategy_audit_trace_tool(
    arguments: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    *,
    user_id: str = "",
    proposal_id: str = "",
    implementation_id: str = "",
    plan_id: str = "",
    commit_id: str = "",
    binding_id: str = "",
    run_id: str = "",
    conversation_id: str = "",
    output_dir: str | Path = "",
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Adapt Agent or legacy arguments to the audit-trace use case."""

    args, ctx = _resolve_call(
        arguments,
        context,
        {
            "user_id": user_id,
            "proposal_id": proposal_id,
            "implementation_id": implementation_id,
            "plan_id": plan_id,
            "commit_id": commit_id,
            "binding_id": binding_id,
            "run_id": run_id,
            "conversation_id": conversation_id,
            "output_dir": output_dir,
            "db_path": db_path,
        },
    )
    return _tool_payload(
        read_strategy_audit_trace(
            user_id=str(_context_value(args, ctx, "user_id", "default")),
            proposal_id=str(args.get("proposal_id") or ""),
            implementation_id=str(args.get("implementation_id") or ""),
            plan_id=str(args.get("plan_id") or ""),
            commit_id=str(args.get("commit_id") or ""),
            binding_id=str(args.get("binding_id") or ""),
            run_id=str(_context_value(args, ctx, "run_id", "")),
            conversation_id=str(
                _context_value(
                    args,
                    ctx,
                    "conversation_id",
                    ctx.get("session_id") or "",
                )
            ),
            output_dir=args.get("output_dir") or ctx.get("output_dir") or "outputs",
            db_path=args.get("db_path") or ctx.get("db_path"),
        ),
        "strategy.get_audit_trace",
    )


__all__ = [
    "execute_active_strategy_proposal_tool",
    "execute_strategy_audit_trace_tool",
    "execute_strategy_context_tool",
]
