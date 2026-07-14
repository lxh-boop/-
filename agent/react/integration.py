from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.communication.integration import (
    approval_refs_from_payload,
    artifact_refs_from_result,
    context_ref_from_bundle,
    publish_agent_message,
    result_summary_payload,
)
from agent.communication.message_types import MessageType

from .observation_types import ObservationEvent, ObservationSeverity, ObservationType
from .observe_store import ObserveStore
from .replan_policy import ReplanPolicy
from .replan_types import ReplanDecision, ReplanDecisionStatus


def record_tool_observation(
    result: Any,
    *,
    context: dict[str, Any] | None = None,
    context_bundle: Any | None = None,
    source_message_id: str = "",
) -> dict[str, Any]:
    context = dict(context or {})
    if not context.get("output_dir"):
        return {}
    result_dict = _plain_result(result)
    event = observation_from_tool_result(
        result_dict,
        context=context,
        context_bundle=context_bundle,
        source_message_id=source_message_id,
    )
    return _save_publish_observation_and_replan(event, context=context, context_bundle=context_bundle)


def record_executor_result_observation(
    result: Any,
    *,
    output_dir: str | Path = "outputs",
    user_id: str = "default",
    conversation_id: str = "",
    run_id: str = "",
    task_id: str = "",
    context_bundle: Any | None = None,
) -> dict[str, Any]:
    result_dict = _plain_result(result)
    success = bool(result_dict.get("success"))
    completion = (
        dict(result_dict.get("llm_completion") or {})
        if isinstance(result_dict.get("llm_completion"), dict)
        else {}
    )
    completion_status = str(completion.get("status") or "").strip().lower()
    next_action = str(completion.get("next_action") or "").strip().lower()

    observation_type = ObservationType.REPORT_READY if success else ObservationType.TASK_FAILED
    severity = ObservationSeverity.INFO if success else ObservationSeverity.HIGH
    if completion_status in {"partial", "missing", "unknown"}:
        observation_type = (
            ObservationType.USER_CLARIFICATION_NEEDED
            if next_action == "ask_user"
            else ObservationType.TASK_PARTIAL_SUCCESS
        )
        severity = ObservationSeverity.MEDIUM
    elif completion_status in {"conflict", "invalid"}:
        observation_type = ObservationType.TASK_FAILED
        severity = ObservationSeverity.HIGH
    elif completion_status == "complete":
        observation_type = ObservationType.REPORT_READY
        severity = ObservationSeverity.INFO

    completion_reason = str(completion.get("reason_summary") or "").strip()
    base_summary = str(
        result_dict.get("message")
        or result_dict.get("answer")
        or ("completed" if success else "failed")
    )
    summary = completion_reason or base_summary
    event = ObservationEvent(
        conversation_id=str(conversation_id or ""),
        run_id=str(run_id or result_dict.get("run_id") or ""),
        task_id=str(task_id or result_dict.get("task_id") or ""),
        source_tool_name=str(result_dict.get("tool_name") or "agent_executor"),
        observation_type=observation_type,
        severity=severity,
        summary=summary[:500],
        detail={
            "success": success,
            "error_count": len(result_dict.get("errors") or []),
            "warning_count": len(result_dict.get("warnings") or []),
            "data_keys": sorted(str(key) for key in (result_dict.get("data") or {}).keys())[:50]
            if isinstance(result_dict.get("data"), dict)
            else [],
            "llm_completion": {
                "status": completion_status,
                "next_action": next_action,
                "produced_outputs": list(completion.get("produced_outputs") or [])[:50],
                "missing_outputs": list(completion.get("missing_outputs") or [])[:50],
                "conflict_outputs": list(completion.get("conflict_outputs") or [])[:50],
                "invalid_reasons": list(completion.get("invalid_reasons") or [])[:50],
                "llm_used": bool(completion.get("llm_used")),
            } if completion else {},
        },
        context_refs=context_ref_from_bundle(context_bundle),
        artifact_refs=artifact_refs_from_result(result_dict),
        approval_refs=approval_refs_from_payload(
            result_dict.get("data") if isinstance(result_dict.get("data"), dict) else {}
        ),
        warnings=[str(item) for item in (result_dict.get("warnings") or [])[:20]],
        error={
            "error_type": str(result_dict.get("error_type") or ""),
            "error_message": str(result_dict.get("error_message") or "")[:500],
        } if not success else {},
    )
    context = {
        "output_dir": output_dir,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "run_id": run_id,
        "task_id": task_id,
        "agent_role": "executor",
    }
    return _save_publish_observation_and_replan(event, context=context, context_bundle=context_bundle)


def observation_from_tool_result(
    result: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    context_bundle: Any | None = None,
    source_message_id: str = "",
) -> ObservationEvent:
    context = dict(context or {})
    success = bool(result.get("success"))
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    observation_type = ObservationType.TOOL_SUCCESS
    severity = ObservationSeverity.INFO
    if not success:
        error_type = str(result.get("error_type") or result.get("status") or "")
        if "permission" in error_type or "unauthorized" in error_type:
            observation_type = ObservationType.TOOL_PERMISSION_BLOCKED
        elif data.get("plan_id") or data.get("token_present") or result.get("requires_confirmation"):
            observation_type = ObservationType.APPROVAL_REQUIRED
        else:
            observation_type = ObservationType.TOOL_ERROR
        severity = ObservationSeverity.HIGH
    elif _is_empty_tool_result(data):
        observation_type = ObservationType.TOOL_EMPTY_RESULT
        severity = ObservationSeverity.MEDIUM
    elif data.get("plan_id") or result.get("requires_confirmation"):
        observation_type = ObservationType.APPROVAL_REQUIRED
        severity = ObservationSeverity.MEDIUM

    return ObservationEvent(
        conversation_id=str(context.get("conversation_id") or context.get("session_id") or ""),
        run_id=str(context.get("run_id") or result.get("run_id") or ""),
        task_id=str(context.get("task_id") or result.get("task_id") or ""),
        source_message_id=str(source_message_id or ""),
        source_tool_name=str(result.get("tool_name") or context.get("tool_name") or ""),
        observation_type=observation_type,
        severity=severity,
        summary=str(result.get("message") or result.get("error_message") or observation_type.value)[:500],
        detail={
            "success": success,
            "data_keys": sorted(str(key) for key in data.keys())[:50],
            "warning_count": len(result.get("warnings") or []),
            "error_count": len(result.get("errors") or []),
        },
        context_refs=context_ref_from_bundle(context_bundle),
        artifact_refs=artifact_refs_from_result(result),
        approval_refs=approval_refs_from_payload(data),
        warnings=[str(item) for item in (result.get("warnings") or [])[:20]],
        error={"error_type": str(result.get("error_type") or ""), "error_message": str(result.get("error_message") or "")[:500]}
        if not success
        else {},
        metadata={"schema": "phase15.observation.v1"},
    )


def attach_observation_refs_to_context_bundle(
    context_bundle: Any | None,
    observation: ObservationEvent | dict[str, Any],
    decision: ReplanDecision | dict[str, Any] | None = None,
) -> None:
    if context_bundle is None:
        return
    event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
    runtime_context = getattr(context_bundle, "runtime_context", None)
    if runtime_context is None:
        return
    refs = getattr(runtime_context, "observation_refs", None)
    if refs is None:
        return
    ref = {
        "observation_id": event.observation_id,
        "observation_type": event.observation_type.value,
        "severity": event.severity.value,
        "task_id": event.task_id,
    }
    if ref not in refs:
        refs.append(ref)
    if event.severity == ObservationSeverity.BLOCKING and event.observation_id not in runtime_context.blocking_observation_ids:
        runtime_context.blocking_observation_ids.append(event.observation_id)
    if decision:
        decision_dict = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision or {})
        replan_ref = {
            "replan_decision_id": str(decision_dict.get("replan_decision_id") or ""),
            "status": str(decision_dict.get("status") or ""),
            "reason": str(decision_dict.get("reason") or ""),
            "scope": str(decision_dict.get("scope") or ""),
        }
        if replan_ref["replan_decision_id"] and replan_ref not in runtime_context.replan_refs:
            runtime_context.replan_refs.append(replan_ref)
            runtime_context.latest_replan_decision_id = replan_ref["replan_decision_id"]


def _save_publish_observation_and_replan(
    event: ObservationEvent,
    *,
    context: dict[str, Any],
    context_bundle: Any | None,
) -> dict[str, Any]:
    user_id = str(context.get("user_id") or "default")
    output_dir = context.get("output_dir") or "outputs"
    saved = ObserveStore(output_dir=output_dir).save_observation(event, user_id=user_id)
    decision = ReplanPolicy().build_replan_decision(saved)
    attach_observation_refs_to_context_bundle(context_bundle, saved, decision)
    observation_refs = [{"observation_id": saved.observation_id, "observation_type": saved.observation_type.value}]
    publish_agent_message(
        output_dir=output_dir,
        user_id=user_id,
        conversation_id=saved.conversation_id,
        run_id=saved.run_id,
        task_id=saved.task_id,
        sender="observe_store",
        receiver=str(context.get("agent_role") or "executor"),
        message_type=MessageType.OBSERVATION_CREATED,
        payload={
            "observation_id": saved.observation_id,
            "observation_type": saved.observation_type.value,
            "status": saved.status.value,
            "severity": saved.severity.value,
            "summary": saved.summary,
            "refs": observation_refs,
        },
        payload_schema="phase15.observation_created.v1",
        context_refs=context_ref_from_bundle(context_bundle),
        artifact_refs=list(saved.artifact_refs or []),
        approval_refs=list(saved.approval_refs or []),
        warnings=list(saved.warnings or []),
    )
    _publish_replan_message(decision, context=context, context_bundle=context_bundle, observation_refs=observation_refs)
    return {"observation": saved.to_dict(), "replan_decision": decision.to_dict()}


def _publish_replan_message(
    decision: ReplanDecision,
    *,
    context: dict[str, Any],
    context_bundle: Any | None,
    observation_refs: list[dict[str, Any]],
) -> None:
    status = decision.status
    message_type = {
        ReplanDecisionStatus.REQUESTED: MessageType.REPLAN_REQUESTED,
        ReplanDecisionStatus.SKIPPED: MessageType.REPLAN_SKIPPED,
        ReplanDecisionStatus.APPLIED: MessageType.REPLAN_APPLIED,
        ReplanDecisionStatus.BLOCKED: MessageType.REPLAN_BLOCKED,
        ReplanDecisionStatus.WAIT_APPROVAL: MessageType.REPLAN_REQUESTED,
    }.get(status, MessageType.REPLAN_SKIPPED)
    publish_agent_message(
        output_dir=context.get("output_dir") or "outputs",
        user_id=str(context.get("user_id") or "default"),
        conversation_id=decision.conversation_id,
        run_id=decision.run_id,
        task_id=decision.task_id,
        sender="replan_policy",
        receiver=str(context.get("agent_role") or "executor"),
        message_type=message_type,
        payload={
            "replan_decision_id": decision.replan_decision_id,
            "status": decision.status.value,
            "reason": decision.reason.value,
            "scope": decision.scope.value,
            "summary": decision.summary,
            "refs": observation_refs,
            "blocked_by": list(decision.blocked_by or []),
        },
        payload_schema="phase15.replan_decision.v1",
        context_refs=context_ref_from_bundle(context_bundle),
        artifact_refs=list(decision.artifact_refs or []),
        warnings=[],
    )


def _plain_result(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return dict(result.to_dict())
    return dict(result or {})


def _is_empty_tool_result(data: dict[str, Any]) -> bool:
    if not data:
        return True
    ignored = {"not_committed", "token_present", "requires_confirmation"}
    meaningful = {key: value for key, value in data.items() if key not in ignored}
    if not meaningful:
        return True
    empty_keys = {"items", "results", "records", "rows", "chunks", "evidence", "sources", "positions"}
    if any(key in meaningful and meaningful.get(key) in (None, [], {}, "") for key in empty_keys):
        non_empty = [value for key, value in meaningful.items() if key not in empty_keys and value not in (None, [], {}, "")]
        return not non_empty
    return False
