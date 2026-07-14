from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time
from typing import Any

from agent.communication.integration import approval_refs_from_payload, publish_agent_message, result_summary_payload
from agent.communication.message_types import MessageType
from agent.session.pending_action_store import get_pending_plan
from agent.tool_engine import AGENT_MAIN, UnifiedToolResult, execute_tool


PLAN_INTENT_TO_TOOL = {
    "capital_change": "capital.change.commit",
    "paper_backfill": "backfill.commit",
    "disable_strategy": "strategy.disable.commit",
    "execute_add_stock": "portfolio.commit_paper_trade",
    "execute_adjust_position": "portfolio.commit_paper_trade",
    "execute_portfolio_rebalance": "portfolio.commit_paper_trade",
    "register_strategy": "approval.confirm_plan",
    "enable_strategy": "approval.confirm_plan",
}


def _failure(tool_name: str, error_type: str, message: str, *, data: dict[str, Any] | None = None) -> UnifiedToolResult:
    started = datetime.now().isoformat(timespec="seconds")
    return UnifiedToolResult(
        success=False,
        tool_name=tool_name,
        message=message,
        data=dict(data or {}),
        errors=[error_type],
        error_type=error_type,
        error_message=message,
        started_at=started,
        finished_at=started,
        duration_ms=0.0,
    )


def execute_confirmed_plan_v2(
    plan_id: str,
    confirmation_token: str,
    user_id: str,
    conversation_id: str = "",
    run_id: str = "",
    db_path: str | Path | None = None,
    output_dir: str | Path = "outputs",
) -> UnifiedToolResult:
    started = time.perf_counter()
    plan_id = str(plan_id or "")
    user_id = str(user_id or "default")
    def _publish_approval_result(result_payload: dict[str, Any], *, intent: str = "", result: UnifiedToolResult | None = None) -> None:
        publish_agent_message(
            output_dir=output_dir,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run_id,
            sender="write_gateway",
            receiver="ui",
            message_type=MessageType.APPROVAL_RESULT_RECEIVED,
            payload={
                "plan_id": plan_id,
                "intent": intent,
                "success": bool(result_payload.get("success")),
                "status": result_payload.get("status") or ("success" if result_payload.get("success") else "failed"),
                "message": str(result_payload.get("message") or "")[:500],
                "tool_name": str(result_payload.get("tool_name") or ""),
            },
            payload_schema="phase13.approval_result.v1",
            approval_refs=approval_refs_from_payload({"plan_id": plan_id, "status": result_payload.get("status") or ""}),
            artifact_refs=[] if result is None else [],
        )

    plan = get_pending_plan(user_id, plan_id, output_dir)
    if not plan:
        _publish_approval_result({"success": False, "status": "plan_not_found", "message": "Pending confirmation plan was not found.", "tool_name": "approval.confirm_plan"})
        return _failure(
            "approval.confirm_plan",
            "plan_not_found",
            "Pending confirmation plan was not found.",
            data={"plan_id": plan_id},
        )
    intent = str(plan.get("intent") or "")
    tool_name = PLAN_INTENT_TO_TOOL.get(intent)
    if not tool_name:
        _publish_approval_result({"success": False, "status": "unsupported_plan_intent", "message": "Unsupported confirmation plan intent.", "tool_name": "approval.confirm_plan"}, intent=intent)
        return _failure(
            "approval.confirm_plan",
            "unsupported_plan_intent",
            "Unsupported confirmation plan intent.",
            data={"plan_id": plan_id, "intent": intent},
        )
    result = execute_tool(
        tool_name,
        {"plan_id": plan_id, "confirmation_token": confirmation_token, "user_id": user_id},
        context={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "session_id": conversation_id,
            "run_id": run_id,
            "db_path": db_path,
            "output_dir": output_dir,
            "plan_intent": intent,
            "plan_id": plan_id,
        },
        agent_type=AGENT_MAIN,
        approval_granted=True,
    )
    if not result.metadata.get("write_gateway"):
        metadata = dict(result.metadata or {})
        metadata["write_gateway"] = {
            "plan_id": plan_id,
            "intent": intent,
            "selected_tool": tool_name,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        wrapped = UnifiedToolResult(
            success=result.success,
            tool_name=result.tool_name,
            data=result.data,
            message=result.message,
            warnings=result.warnings,
            errors=result.errors,
            error_type=result.error_type,
            error_message=result.error_message,
            sources=result.sources,
            metadata=metadata,
            artifact_id=result.artifact_id,
            started_at=result.started_at,
            finished_at=result.finished_at,
            duration_ms=result.duration_ms,
            retry_count=result.retry_count,
            circuit_state=result.circuit_state,
            schema_version=result.schema_version,
        )
        _publish_approval_result(result_summary_payload(wrapped), intent=intent, result=wrapped)
        return wrapped
    _publish_approval_result(result_summary_payload(result), intent=intent, result=result)
    return result


def execute_confirmed_plan_legacy_dict(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return execute_confirmed_plan_v2(*args, **kwargs).to_legacy_dict()
