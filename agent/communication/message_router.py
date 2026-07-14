from __future__ import annotations

from agent.communication.message_types import AgentMessage, MessageEnvelope, MessageType, MessageVisibility


class MessageRouter:
    def route_message(self, message: AgentMessage) -> MessageEnvelope:
        route = self._route_for(message)
        visibility = self._visibility_for(message)
        return MessageEnvelope(
            message=message,
            route=route,
            visibility=visibility,
            trace_id=message.run_id or message.conversation_id,
        )

    def route_to_executor(self, message: AgentMessage) -> MessageEnvelope:
        return MessageEnvelope(message=message, route=["executor"], visibility=self._visibility_for(message))

    def route_to_tool_executor(self, message: AgentMessage) -> MessageEnvelope:
        return MessageEnvelope(message=message, route=["tool_executor"], visibility=MessageVisibility.TOOL_ONLY)

    def route_to_write_gateway(self, message: AgentMessage) -> MessageEnvelope:
        return MessageEnvelope(message=message, route=["write_gateway"], visibility=MessageVisibility.TOOL_ONLY)

    def route_to_ui(self, message: AgentMessage) -> MessageEnvelope:
        return MessageEnvelope(message=message, route=["ui"], visibility=MessageVisibility.UI_VISIBLE)

    def route_to_audit(self, message: AgentMessage) -> MessageEnvelope:
        return MessageEnvelope(message=message, route=["audit"], visibility=MessageVisibility.AUDIT_ONLY)

    def _route_for(self, message: AgentMessage) -> list[str]:
        message_type = message.message_type
        if message_type in {MessageType.USER_REQUEST, MessageType.GOAL_PARSED, MessageType.TASK_PLANNED}:
            return ["executor"]
        if message_type == MessageType.TOOL_CALL_REQUESTED:
            return ["tool_executor"]
        if message_type in {MessageType.APPROVAL_REQUESTED, MessageType.APPROVAL_RESULT_RECEIVED}:
            return ["write_gateway", "ui", "audit"]
        if message_type in {MessageType.FINAL_REPORT, MessageType.REPORT_DRAFTED}:
            return ["ui", "audit"]
        if message_type in {
            MessageType.HANDOFF_REQUESTED,
            MessageType.HANDOFF_ACCEPTED,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_BLOCKED,
        }:
            return ["ui", "audit"]
        if message_type in {MessageType.ERROR_RAISED, MessageType.WARNING_RAISED}:
            return ["audit", "ui"]
        return ["audit"]

    @staticmethod
    def _visibility_for(message: AgentMessage) -> MessageVisibility:
        if message.message_type == MessageType.TOOL_CALL_REQUESTED:
            return MessageVisibility.TOOL_ONLY
        if message.message_type in {MessageType.ERROR_RAISED, MessageType.WARNING_RAISED}:
            return MessageVisibility.AUDIT_ONLY
        if message.message_type in {MessageType.FINAL_REPORT, MessageType.REPORT_DRAFTED}:
            return MessageVisibility.UI_VISIBLE
        if message.message_type in {
            MessageType.HANDOFF_REQUESTED,
            MessageType.HANDOFF_ACCEPTED,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_BLOCKED,
        }:
            return MessageVisibility.UI_VISIBLE
        if message.message_type in {MessageType.APPROVAL_REQUESTED, MessageType.APPROVAL_RESULT_RECEIVED}:
            return MessageVisibility.UI_VISIBLE
        return MessageVisibility.LLM_VISIBLE
