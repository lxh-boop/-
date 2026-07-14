from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.communication.message_types import AgentMessage, MessageVisibility


SECRET_KEYS = {
    "api_key",
    "authorization",
    "authorization_header",
    "confirmation_token",
    "confirmation_token_hash",
    "cookie",
    "llm_api_key",
    "password",
    "secret",
    "tushare_token",
    "token",
}

SYSTEM_ONLY_KEYS = {
    "db_path",
    "database_path",
    "connection_string",
    "internal_file_path",
    "local_path",
    "output_dir",
    "path",
}

AUDIT_ONLY_KEYS = {
    "internal_stack",
    "raw_trace",
    "stack",
    "stack_trace",
    "traceback",
}

TOOL_ONLY_KEYS = {
    "complete_payload",
    "full_payload",
    "full_result",
    "full_result_ref",
    "raw_evidence",
    "raw_payload",
    "raw_positions",
}

LLM_VISIBLE_KEYS = {
    "answer",
    "artifact_id",
    "artifact_refs",
    "context_id",
    "conversation_id",
    "created_at",
    "evidence_summary",
    "message",
    "message_id",
    "pending_plan_id",
    "plan_hash",
    "plan_id",
    "proposal_summary",
    "refs",
    "run_id",
    "source_refs",
    "status",
    "summary",
    "task_id",
    "token_present",
    "tool_call_id",
    "tool_name",
    "user_id",
}


@dataclass(frozen=True)
class MessagePolicy:
    default_visibility: MessageVisibility = MessageVisibility.LLM_VISIBLE
    secret_keys: set[str] = field(default_factory=lambda: set(SECRET_KEYS))
    system_only_keys: set[str] = field(default_factory=lambda: set(SYSTEM_ONLY_KEYS))
    audit_only_keys: set[str] = field(default_factory=lambda: set(AUDIT_ONLY_KEYS))
    tool_only_keys: set[str] = field(default_factory=lambda: set(TOOL_ONLY_KEYS))
    llm_visible_keys: set[str] = field(default_factory=lambda: set(LLM_VISIBLE_KEYS))

    @classmethod
    def default(cls) -> "MessagePolicy":
        return cls()

    def classify_field(
        self,
        key: str,
        value: Any = None,
        path: tuple[str, ...] = (),
    ) -> MessageVisibility:
        del value
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered in self.secret_keys or any(marker in lowered for marker in ("api_key", "password", "secret")):
            return MessageVisibility.SECRET
        if lowered in {"confirmation_token", "confirmation_token_hash"}:
            return MessageVisibility.SECRET
        if lowered in self.audit_only_keys or any(marker in joined for marker in ("traceback", "stack_trace", "internal_stack")):
            return MessageVisibility.AUDIT_ONLY
        if lowered in self.system_only_keys:
            return MessageVisibility.SYSTEM_ONLY
        if lowered in self.tool_only_keys or joined.endswith(".raw_evidence") or joined.endswith(".raw_positions"):
            return MessageVisibility.TOOL_ONLY
        if lowered in self.llm_visible_keys:
            return MessageVisibility.LLM_VISIBLE
        return self.default_visibility

    def classify_message(self, message: AgentMessage | dict[str, Any]) -> MessageVisibility:
        data = message.to_dict() if hasattr(message, "to_dict") else dict(message or {})
        encoded_keys = " ".join(str(key).lower() for key in _walk_keys(data))
        if any(secret in encoded_keys for secret in self.secret_keys):
            return MessageVisibility.SECRET
        if any(system_key in encoded_keys for system_key in self.system_only_keys):
            return MessageVisibility.SYSTEM_ONLY
        return self.default_visibility

    def can_deliver(self, visibility: MessageVisibility | str, target: str, *, permission_scope: str = "read") -> bool:
        if not isinstance(visibility, MessageVisibility):
            visibility = MessageVisibility(str(visibility))
        target = str(target or "").lower()
        permission_scope = str(permission_scope or "read").lower()
        if visibility == MessageVisibility.SECRET:
            return False
        if target == "llm":
            return visibility == MessageVisibility.LLM_VISIBLE
        if target == "ui":
            return visibility in {MessageVisibility.LLM_VISIBLE, MessageVisibility.UI_VISIBLE}
        if target == "tool":
            if visibility == MessageVisibility.AUDIT_ONLY:
                return False
            if visibility == MessageVisibility.SYSTEM_ONLY:
                return permission_scope in {"system", "write", "admin"}
            return visibility in {
                MessageVisibility.LLM_VISIBLE,
                MessageVisibility.UI_VISIBLE,
                MessageVisibility.TOOL_ONLY,
            }
        if target == "audit":
            return True
        if target in {"system", "internal"}:
            return visibility != MessageVisibility.SECRET
        return visibility == MessageVisibility.LLM_VISIBLE

    def can_show_to_llm(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "llm")

    def can_show_to_ui(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "ui")

    def requires_redaction(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.classify_field(key, value=value, path=path) in {
            MessageVisibility.SECRET,
            MessageVisibility.SYSTEM_ONLY,
            MessageVisibility.AUDIT_ONLY,
            MessageVisibility.TOOL_ONLY,
        }


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(item))
        return keys
    if isinstance(value, list):
        keys = []
        for item in value:
            keys.extend(_walk_keys(item))
        return keys
    return []

