from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .observation_types import (
    ObservationEvent,
    ObservationSeverity,
    ObservationType,
    ObservationVisibility,
)


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
    "connection_string",
    "database_path",
    "db_path",
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
    "raw_tool_payload",
}

LLM_VISIBLE_KEYS = {
    "approval_refs",
    "artifact_id",
    "artifact_refs",
    "context_id",
    "context_refs",
    "conversation_id",
    "created_at",
    "error_type",
    "evidence_summary",
    "memory_refs",
    "message",
    "message_id",
    "message_refs",
    "observation_id",
    "observation_type",
    "parent_task_id",
    "plan_hash",
    "plan_id",
    "refs",
    "replan_hint",
    "run_id",
    "severity",
    "source_message_id",
    "source_refs",
    "source_tool_name",
    "status",
    "summary",
    "task_id",
    "token_present",
    "tool_call_id",
    "tool_call_refs",
    "tool_name",
}

REPLAN_OBSERVATION_TYPES = {
    ObservationType.TOOL_EMPTY_RESULT,
    ObservationType.TOOL_ERROR,
    ObservationType.TOOL_PERMISSION_BLOCKED,
    ObservationType.CONTEXT_INSUFFICIENT,
    ObservationType.EVIDENCE_INSUFFICIENT,
    ObservationType.APPROVAL_REQUIRED,
    ObservationType.APPROVAL_DENIED,
    ObservationType.TASK_PARTIAL_SUCCESS,
    ObservationType.TASK_FAILED,
    ObservationType.USER_CLARIFICATION_NEEDED,
}

SEVERITY_BY_TYPE = {
    ObservationType.TOOL_SUCCESS: ObservationSeverity.INFO,
    ObservationType.MEMORY_HIT: ObservationSeverity.INFO,
    ObservationType.REPORT_READY: ObservationSeverity.INFO,
    ObservationType.MEMORY_EMPTY: ObservationSeverity.LOW,
    ObservationType.APPROVAL_REQUIRED: ObservationSeverity.MEDIUM,
    ObservationType.TOOL_EMPTY_RESULT: ObservationSeverity.MEDIUM,
    ObservationType.EVIDENCE_INSUFFICIENT: ObservationSeverity.MEDIUM,
    ObservationType.CONTEXT_INSUFFICIENT: ObservationSeverity.HIGH,
    ObservationType.TOOL_ERROR: ObservationSeverity.HIGH,
    ObservationType.TOOL_PERMISSION_BLOCKED: ObservationSeverity.HIGH,
    ObservationType.APPROVAL_DENIED: ObservationSeverity.BLOCKING,
    ObservationType.TASK_FAILED: ObservationSeverity.BLOCKING,
}


@dataclass(frozen=True)
class ObservePolicy:
    default_visibility: ObservationVisibility = ObservationVisibility.LLM_VISIBLE
    secret_keys: set[str] = field(default_factory=lambda: set(SECRET_KEYS))
    system_only_keys: set[str] = field(default_factory=lambda: set(SYSTEM_ONLY_KEYS))
    audit_only_keys: set[str] = field(default_factory=lambda: set(AUDIT_ONLY_KEYS))
    tool_only_keys: set[str] = field(default_factory=lambda: set(TOOL_ONLY_KEYS))
    llm_visible_keys: set[str] = field(default_factory=lambda: set(LLM_VISIBLE_KEYS))

    @classmethod
    def default(cls) -> "ObservePolicy":
        return cls()

    def classify_field(
        self,
        key: str,
        value: Any = None,
        path: tuple[str, ...] = (),
    ) -> ObservationVisibility:
        del value
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered == "token_present":
            return ObservationVisibility.LLM_VISIBLE
        if lowered in self.secret_keys or any(marker in lowered for marker in ("api_key", "password", "secret")):
            return ObservationVisibility.SECRET
        if "confirmation_token" in lowered or lowered == "tushare_token":
            return ObservationVisibility.SECRET
        if lowered in self.audit_only_keys or any(marker in joined for marker in ("traceback", "stack_trace", "internal_stack")):
            return ObservationVisibility.AUDIT_ONLY
        if lowered in self.system_only_keys:
            return ObservationVisibility.SYSTEM_ONLY
        if lowered in self.tool_only_keys or joined.endswith(".raw_evidence") or joined.endswith(".raw_positions") or joined.endswith(".raw_tool_payload"):
            return ObservationVisibility.TOOL_ONLY
        if lowered in self.llm_visible_keys:
            return ObservationVisibility.LLM_VISIBLE
        return self.default_visibility

    def classify_observation(self, observation: ObservationEvent | dict[str, Any] | ObservationType | str) -> ObservationSeverity:
        observation_type = _observation_type_from_value(observation)
        if isinstance(observation, ObservationEvent):
            return observation.severity or SEVERITY_BY_TYPE.get(observation_type, ObservationSeverity.INFO)
        if isinstance(observation, dict) and observation.get("severity"):
            return ObservationSeverity.from_value(observation.get("severity"))
        return SEVERITY_BY_TYPE.get(observation_type, ObservationSeverity.INFO)

    def can_deliver(
        self,
        visibility: ObservationVisibility | str,
        target: str,
        *,
        permission_scope: str = "read",
    ) -> bool:
        if not isinstance(visibility, ObservationVisibility):
            visibility = ObservationVisibility.from_value(visibility)
        target = str(target or "").lower()
        permission_scope = str(permission_scope or "read").lower()
        if visibility == ObservationVisibility.SECRET:
            return False
        if target == "llm":
            return visibility == ObservationVisibility.LLM_VISIBLE
        if target == "ui":
            return visibility in {ObservationVisibility.LLM_VISIBLE, ObservationVisibility.UI_VISIBLE}
        if target == "context":
            return visibility == ObservationVisibility.LLM_VISIBLE
        if target == "tool":
            if visibility == ObservationVisibility.AUDIT_ONLY:
                return False
            if visibility == ObservationVisibility.SYSTEM_ONLY:
                return permission_scope in {"admin", "system", "write"}
            return visibility in {
                ObservationVisibility.LLM_VISIBLE,
                ObservationVisibility.UI_VISIBLE,
                ObservationVisibility.TOOL_ONLY,
            }
        if target in {"audit", "system", "internal"}:
            return visibility != ObservationVisibility.SECRET
        return visibility == ObservationVisibility.LLM_VISIBLE

    def can_show_to_llm(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "llm")

    def can_show_to_ui(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "ui")

    def can_store(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.classify_field(key, value=value, path=path) != ObservationVisibility.SECRET

    def requires_replan_check(self, observation: ObservationEvent | dict[str, Any] | ObservationType | str) -> bool:
        return _observation_type_from_value(observation) in REPLAN_OBSERVATION_TYPES

    def requires_redaction(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.classify_field(key, value=value, path=path) in {
            ObservationVisibility.SECRET,
            ObservationVisibility.SYSTEM_ONLY,
            ObservationVisibility.AUDIT_ONLY,
            ObservationVisibility.TOOL_ONLY,
        }


def _observation_type_from_value(value: ObservationEvent | dict[str, Any] | ObservationType | str) -> ObservationType:
    if isinstance(value, ObservationEvent):
        return value.observation_type
    if isinstance(value, dict):
        return ObservationType.from_value(value.get("observation_type") or value.get("type"))
    return ObservationType.from_value(value)
