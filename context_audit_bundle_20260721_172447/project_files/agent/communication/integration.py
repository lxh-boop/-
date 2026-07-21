from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.communication.message_bus import MessageBus
from agent.communication.message_store import MessageStore
from agent.communication.message_types import AgentMessage, MessageType


def publish_agent_message(
    *,
    output_dir: str | Path = "outputs",
    user_id: str = "default",
    conversation_id: str = "",
    run_id: str = "",
    task_id: str = "",
    parent_task_id: str = "",
    sender: str,
    receiver: str,
    message_type: MessageType,
    payload: dict[str, Any] | None = None,
    payload_schema: str = "",
    context_refs: list[dict[str, Any]] | None = None,
    artifact_refs: list[dict[str, Any]] | None = None,
    approval_refs: list[dict[str, Any]] | None = None,
    tool_call_refs: list[dict[str, Any]] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    try:
        message = AgentMessage(
            conversation_id=str(conversation_id or ""),
            run_id=str(run_id or ""),
            task_id=str(task_id or ""),
            parent_task_id=str(parent_task_id or ""),
            sender=str(sender or ""),
            receiver=str(receiver or ""),
            message_type=message_type,
            payload=dict(payload or {}),
            payload_schema=str(payload_schema or ""),
            context_refs=list(context_refs or []),
            artifact_refs=list(artifact_refs or []),
            approval_refs=list(approval_refs or []),
            tool_call_refs=list(tool_call_refs or []),
            source_refs=list(source_refs or []),
            warnings=[str(item) for item in (warnings or [])],
            error=dict(error or {}),
            metadata={"user_id": str(user_id or "default"), **dict(metadata or {})},
        )
        MessageBus(store=MessageStore(output_dir=output_dir)).publish(message)
        return message.message_id
    except Exception:
        return ""


def context_ref_from_bundle(bundle: Any | None) -> list[dict[str, Any]]:
    if bundle is None:
        return []
    try:
        return [
            {
                "context_id": str(getattr(bundle, "context_id", "") or ""),
                "run_id": str(getattr(bundle, "run_id", "") or ""),
                "conversation_id": str(getattr(bundle, "conversation_id", "") or ""),
                "task_id": str(getattr(bundle, "task_id", "") or ""),
            }
        ]
    except Exception:
        return []


def artifact_refs_from_result(result: dict[str, Any] | Any) -> list[dict[str, Any]]:
    try:
        data = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    except Exception:
        return []
    refs: list[dict[str, Any]] = []
    artifact_id = str(data.get("artifact_id") or "")
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    artifact_ref = metadata.get("artifact_ref") if isinstance(metadata.get("artifact_ref"), dict) else {}
    if artifact_ref:
        refs.append(
            {
                "artifact_id": str(artifact_ref.get("artifact_id") or artifact_id or ""),
                "artifact_type": str(artifact_ref.get("artifact_type") or "tool_result"),
                "tool_name": str(artifact_ref.get("tool_name") or data.get("tool_name") or ""),
                "produced_outputs": artifact_ref.get("produced_outputs") or [],
            }
        )
    elif artifact_id:
        refs.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": "tool_result",
                "tool_name": str(data.get("tool_name") or ""),
                "produced_outputs": [],
            }
        )
    return [ref for ref in refs if ref.get("artifact_id")]


def approval_refs_from_payload(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    data = dict(payload or {})
    plan_id = str(data.get("plan_id") or data.get("pending_plan_id") or "")
    if not plan_id:
        return []
    return [
        {
            "plan_id": plan_id,
            "plan_hash": str(data.get("plan_hash") or ""),
            "status": str(data.get("confirmation_status") or data.get("approval_status") or data.get("status") or ""),
            "token_present": bool(data.get("token_present") or data.get("confirmation_token")),
        }
    ]


def result_summary_payload(result: dict[str, Any] | Any) -> dict[str, Any]:
    data = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
    payload_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    return {
        "success": bool(data.get("success")),
        "tool_name": str(data.get("tool_name") or ""),
        "message": str(data.get("message") or "")[:500],
        "artifact_id": str(data.get("artifact_id") or ""),
        "plan_id": str(payload_data.get("plan_id") or ""),
        "requires_confirmation": bool(data.get("requires_confirmation") or payload_data.get("requires_confirmation")),
    }

