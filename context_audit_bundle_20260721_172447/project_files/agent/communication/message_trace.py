from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from agent.communication.message_types import AgentMessage


@dataclass
class MessageTrace:
    trace_id: str = field(default_factory=lambda: f"trace_{uuid4().hex[:12]}")
    run_id: str = ""
    message_ids: list[str] = field(default_factory=list)
    parent_child_edges: list[dict[str, str]] = field(default_factory=list)
    tool_call_edges: list[dict[str, str]] = field(default_factory=list)
    artifact_edges: list[dict[str, str]] = field(default_factory=list)
    approval_edges: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "message_ids": list(self.message_ids),
            "parent_child_edges": list(self.parent_child_edges),
            "tool_call_edges": list(self.tool_call_edges),
            "artifact_edges": list(self.artifact_edges),
            "approval_edges": list(self.approval_edges),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def build_message_trace(messages: list[AgentMessage], *, trace_id: str = "") -> MessageTrace:
    trace = MessageTrace(trace_id=trace_id or f"trace_{uuid4().hex[:12]}")
    task_message_by_task: dict[str, str] = {}
    for message in messages:
        if not trace.run_id and message.run_id:
            trace.run_id = message.run_id
        trace.message_ids.append(message.message_id)
        if message.task_id:
            task_message_by_task[message.task_id] = message.message_id
        if message.parent_task_id:
            trace.parent_child_edges.append(
                {
                    "parent_task_id": message.parent_task_id,
                    "child_task_id": message.task_id,
                    "parent_message_id": task_message_by_task.get(message.parent_task_id, ""),
                    "child_message_id": message.message_id,
                }
            )
        for ref in message.tool_call_refs:
            trace.tool_call_edges.append(
                {
                    "message_id": message.message_id,
                    "tool_call_id": str(ref.get("tool_call_id") or ref.get("id") or ""),
                    "tool_name": str(ref.get("tool_name") or ""),
                }
            )
        for ref in message.artifact_refs:
            trace.artifact_edges.append(
                {
                    "message_id": message.message_id,
                    "artifact_id": str(ref.get("artifact_id") or ref.get("id") or ""),
                    "artifact_type": str(ref.get("artifact_type") or ""),
                }
            )
        for ref in message.approval_refs:
            trace.approval_edges.append(
                {
                    "message_id": message.message_id,
                    "plan_id": str(ref.get("plan_id") or ref.get("pending_plan_id") or ""),
                    "approval_id": str(ref.get("approval_id") or ""),
                }
            )
        if message.error:
            trace.errors.append({"message_id": message.message_id, **dict(message.error)})
        for warning in message.warnings:
            trace.warnings.append(str(warning))
    return trace

