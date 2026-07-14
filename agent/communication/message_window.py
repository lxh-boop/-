from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from agent.communication.message_sanitizer import MessageSanitizer
from agent.communication.message_types import AgentMessage, MessageSummary, MessageType


REQUIRED_MESSAGE_TYPES = {
    MessageType.USER_REQUEST,
    MessageType.FINAL_REPORT,
}


class MessageWindow:
    def __init__(self, *, default_budget: int = 6000, sanitizer: MessageSanitizer | None = None) -> None:
        self.default_budget = int(default_budget or 6000)
        self.sanitizer = sanitizer or MessageSanitizer()

    def estimate_message_size(self, message: AgentMessage | dict[str, Any]) -> int:
        data = message.to_dict() if hasattr(message, "to_dict") else dict(message or {})
        return len(json.dumps(data, ensure_ascii=False, default=str))

    def keep_required_messages(self, messages: list[AgentMessage]) -> list[AgentMessage]:
        return [message for message in messages if message.message_type in REQUIRED_MESSAGE_TYPES]

    def summarize_old_messages(self, messages: list[AgentMessage]) -> list[MessageSummary]:
        return [self._summary_for(message) for message in messages]

    def trim_messages_to_budget(
        self,
        messages: list[AgentMessage],
        *,
        max_chars: int | None = None,
        target: str = "llm",
    ) -> list[AgentMessage]:
        budget = int(max_chars or self.default_budget)
        prepared = [self._prepare_message(message, target=target) for message in messages]
        required_ids = {message.message_id for message in self.keep_required_messages(prepared)}
        selected: list[AgentMessage] = []
        total = 0
        for message in reversed(prepared):
            size = self.estimate_message_size(message)
            if message.message_id in required_ids or total + size <= budget:
                selected.append(message)
                total += size
        selected_ids = {message.message_id for message in selected}
        omitted = [message for message in prepared if message.message_id not in selected_ids]
        if omitted:
            summary_message = AgentMessage(
                sender="message_window",
                receiver="context",
                message_type=MessageType.CONTEXT_CREATED,
                payload_schema="message_summary.v1",
                payload={
                    "summarized_messages": [summary.to_dict() for summary in self.summarize_old_messages(omitted)],
                    "summary": f"{len(omitted)} older messages summarized",
                },
            )
            if self.estimate_message_size(summary_message) + sum(self.estimate_message_size(item) for item in selected) <= budget or not selected:
                selected.append(summary_message)
        return list(reversed(selected))

    def _prepare_message(self, message: AgentMessage, *, target: str) -> AgentMessage:
        if message.message_type == MessageType.TOOL_RESULT_RECEIVED:
            payload = self.sanitizer.sanitize_for_llm(message.payload) if target == "llm" else self.sanitizer.sanitize_for_ui(message.payload)
            return replace(
                message,
                payload={
                    "success": payload.get("success"),
                    "tool_name": payload.get("tool_name"),
                    "message": str(payload.get("message") or "")[:300],
                    "artifact_refs": list(message.artifact_refs or payload.get("artifact_refs") or []),
                    "summary": payload.get("summary") or payload.get("result_summary") or "",
                },
            )
        if message.message_type == MessageType.APPROVAL_REQUESTED:
            payload = self.sanitizer.sanitize_for_llm(message.payload) if target == "llm" else self.sanitizer.sanitize_for_ui(message.payload)
            return replace(
                message,
                payload={
                    "plan_id": payload.get("plan_id") or payload.get("pending_plan_id"),
                    "plan_hash": payload.get("plan_hash"),
                    "status": payload.get("status"),
                    "token_present": bool(payload.get("token_present")),
                    "proposal_summary": payload.get("proposal_summary") or payload.get("summary") or "",
                },
            )
        data = message.to_dict()
        if target == "ui":
            sanitized = self.sanitizer.sanitize_for_ui(data)
        elif target == "tool":
            sanitized = self.sanitizer.sanitize_for_tool(data)
        elif target == "audit":
            sanitized = self.sanitizer.sanitize_for_audit(data)
        else:
            sanitized = self.sanitizer.sanitize_for_llm(data)
        return AgentMessage.from_dict({**message.to_dict(), **sanitized})

    def _summary_for(self, message: AgentMessage) -> MessageSummary:
        payload = self.sanitizer.sanitize_for_llm(message.payload)
        summary = str(
            payload.get("summary")
            or payload.get("message")
            or payload.get("answer")
            or message.message_type.value
        )[:240]
        refs = {
            "context_refs": message.context_refs,
            "artifact_refs": message.artifact_refs,
            "approval_refs": message.approval_refs,
            "tool_call_refs": message.tool_call_refs,
            "source_refs": message.source_refs,
        }
        return MessageSummary(
            message_id=message.message_id,
            message_type=message.message_type,
            sender=message.sender,
            receiver=message.receiver,
            summary=summary,
            refs={key: value for key, value in refs.items() if value},
            original_size=self.estimate_message_size(message),
        )

