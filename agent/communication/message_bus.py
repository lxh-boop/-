from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

from agent.communication.message_router import MessageRouter
from agent.communication.message_store import MessageStore
from agent.communication.message_trace import MessageTrace
from agent.communication.message_types import AgentMessage, MessageEnvelope, MessageType


MessageHandler = Callable[[AgentMessage], Any]


class MessageBus:
    def __init__(
        self,
        *,
        store: MessageStore | None = None,
        router: MessageRouter | None = None,
    ) -> None:
        self.store = store or MessageStore()
        self.router = router or MessageRouter()
        self._subscribers: dict[MessageType, list[MessageHandler]] = defaultdict(list)
        self._published_ids: set[str] = set()

    def publish(self, message: AgentMessage | dict[str, Any]) -> MessageEnvelope:
        msg = message if isinstance(message, AgentMessage) else AgentMessage.from_dict(dict(message or {}))
        if msg.message_id not in self._published_ids:
            self.store.save_message(msg)
            self._published_ids.add(msg.message_id)
        return self.router.route_message(msg)

    def publish_many(self, messages: list[AgentMessage | dict[str, Any]]) -> list[MessageEnvelope]:
        return [self.publish(message) for message in messages]

    def subscribe(self, message_type: MessageType | str, handler: MessageHandler) -> None:
        if not isinstance(message_type, MessageType):
            message_type = MessageType(str(message_type))
        self._subscribers[message_type].append(handler)

    def dispatch(self, envelope: MessageEnvelope) -> list[Any]:
        handlers = list(self._subscribers.get(envelope.message.message_type) or [])
        if not handlers:
            return []
        results: list[Any] = []
        for handler in handlers:
            try:
                results.append(handler(envelope.message))
            except Exception as exc:
                error_message = AgentMessage(
                    conversation_id=envelope.message.conversation_id,
                    run_id=envelope.message.run_id,
                    task_id=envelope.message.task_id,
                    sender="message_bus",
                    receiver="audit",
                    message_type=MessageType.ERROR_RAISED,
                    payload={
                        "source_message_id": envelope.message.message_id,
                        "handler": getattr(handler, "__name__", "handler"),
                    },
                    error={
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:500],
                    },
                    metadata={"user_id": envelope.message.metadata.get("user_id", "default")},
                )
                self.publish(error_message)
                results.append(error_message)
        return results

    def get_trace(self, run_id: str, *, user_id: str = "default") -> MessageTrace:
        return self.store.build_trace(run_id, user_id=user_id)

