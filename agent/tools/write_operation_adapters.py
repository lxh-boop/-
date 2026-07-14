from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.services.write_operation_service import write_operation_service
from agent.tools.strategy_builder_tool import prepare_strategy_change
from agent.tools.strategy_management_tool import manage_strategy


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


def _session_id(context: dict[str, Any]) -> str:
    return str(context.get("session_id") or context.get("conversation_id") or "")


def strategy_disable_preview_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.create_strategy_disable_proposal(
        user_id=str(_context_value(args, context, "user_id", "default")),
        strategy_id=str(args.get("strategy_id") or ""),
        version=str(args.get("strategy_version") or args.get("version") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def strategy_builder_preview_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return prepare_strategy_change(
        user_id=str(_context_value(args, context, "user_id", "default")),
        requirement=str(args.get("requirement") or context.get("query") or ""),
        parameters=args.get("parameters") if isinstance(args.get("parameters"), dict) else dict(args or {}),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def strategy_management_preview_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return manage_strategy(
        user_id=str(_context_value(args, context, "user_id", "default")),
        action=str(args.get("action") or "list"),
        strategy_id=str(args.get("strategy_id") or ""),
        version=str(args.get("strategy_version") or args.get("version") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def strategy_disable_commit_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.commit_strategy_disable(
        user_id=str(_context_value(args, context, "user_id", "default")),
        plan_id=str(args.get("plan_id") or ""),
        confirmation_token=str(args.get("confirmation_token") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def capital_change_preview_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.create_capital_change_proposal(
        user_id=str(_context_value(args, context, "user_id", "default")),
        flow_type=str(args.get("flow_type") or ""),
        amount=float(args.get("amount") or 0.0),
        effective_date=str(args.get("effective_date") or ""),
        reason=str(args.get("reason") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def capital_change_commit_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.commit_capital_change(
        user_id=str(_context_value(args, context, "user_id", "default")),
        plan_id=str(args.get("plan_id") or ""),
        confirmation_token=str(args.get("confirmation_token") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def backfill_preview_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.create_backfill_proposal(
        user_id=str(_context_value(args, context, "user_id", "default")),
        start_date=str(args.get("start_date") or ""),
        end_date=str(args.get("end_date") or "latest"),
        initial_cash=args.get("initial_cash"),
        resume=bool(args.get("resume", True)),
        force=bool(args.get("force", False)),
        skip_news=bool(args.get("skip_news", False)),
        strategy=str(args.get("strategy") or "hierarchical_top10"),
        top_k=int(args.get("top_k") or 15),
        entry_top_k=int(args.get("entry_top_k") or 10),
        hold_buffer_rank=int(args.get("hold_buffer_rank") or 15),
        max_positions=int(args.get("max_positions") or 10),
        continue_on_error=bool(args.get("continue_on_error", False)),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def backfill_commit_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.commit_backfill(
        user_id=str(_context_value(args, context, "user_id", "default")),
        plan_id=str(args.get("plan_id") or ""),
        confirmation_token=str(args.get("confirmation_token") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )


def approval_confirm_plan_adapter(args: dict[str, Any], context: dict[str, Any]) -> Any:
    return write_operation_service.confirm_existing_plan(
        user_id=str(_context_value(args, context, "user_id", "default")),
        plan_id=str(args.get("plan_id") or ""),
        confirmation_token=str(args.get("confirmation_token") or ""),
        output_dir=_output_dir(context),
        db_path=_db_path(context),
        session_id=_session_id(context),
    )
