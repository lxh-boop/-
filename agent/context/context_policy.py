from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ContextVisibility(str, Enum):
    LLM_VISIBLE = "llm_visible"
    TOOL_ONLY = "tool_only"
    SYSTEM_ONLY = "system_only"
    UI_VISIBLE = "ui_visible"
    AUDIT_ONLY = "audit_only"
    SECRET = "secret"


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
    "path",
    "output_dir",
}

AUDIT_ONLY_KEYS = {
    "internal_stack",
    "stack",
    "stack_trace",
    "traceback",
    "raw_trace",
}

TOOL_ONLY_KEYS = {
    "raw_evidence",
    "raw_positions",
    "full_result",
    "full_result_ref",
    "complete_payload",
}

LLM_VISIBLE_KEYS = {
    "account_summary",
    "artifact_id",
    "artifact_refs",
    "business_constraints",
    "constraints",
    "conversation_id",
    "evidence_summary",
    "locale",
    "latest_replan_decision_id",
    "latest_handoff_trace_id",
    "handoff_refs",
    "handoff_role_summaries",
    "blocking_observation_ids",
    "observation_id",
    "observation_refs",
    "pending_plan_id",
    "plan_hash",
    "positions_summary",
    "produced_outputs",
    "required_refs",
    "risk_summary",
    "run_id",
    "replan_decision_id",
    "replan_refs",
    "source_refs",
    "status",
    "task_id",
    "task_plan",
    "token_present",
    "user_goal",
    "user_id",
}


@dataclass(frozen=True)
class ContextPolicy:
    default_visibility: ContextVisibility = ContextVisibility.LLM_VISIBLE
    secret_keys: set[str] = field(default_factory=lambda: set(SECRET_KEYS))
    system_only_keys: set[str] = field(default_factory=lambda: set(SYSTEM_ONLY_KEYS))
    audit_only_keys: set[str] = field(default_factory=lambda: set(AUDIT_ONLY_KEYS))
    tool_only_keys: set[str] = field(default_factory=lambda: set(TOOL_ONLY_KEYS))
    llm_visible_keys: set[str] = field(default_factory=lambda: set(LLM_VISIBLE_KEYS))

    @classmethod
    def default(cls) -> "ContextPolicy":
        return cls()

    def visibility_for(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> ContextVisibility:
        del value
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered in self.secret_keys or any(marker in lowered for marker in ["api_key", "password", "secret"]):
            return ContextVisibility.SECRET
        if lowered in {"confirmation_token", "confirmation_token_hash"}:
            return ContextVisibility.SECRET
        if lowered in self.audit_only_keys or any(marker in joined for marker in ["traceback", "stack_trace", "internal_stack"]):
            return ContextVisibility.AUDIT_ONLY
        if lowered in self.system_only_keys:
            return ContextVisibility.SYSTEM_ONLY
        if lowered in self.tool_only_keys or joined.endswith(".raw_evidence") or joined.endswith(".raw_positions"):
            return ContextVisibility.TOOL_ONLY
        if lowered in self.llm_visible_keys:
            return ContextVisibility.LLM_VISIBLE
        return self.default_visibility

    def is_visible_for(
        self,
        key: str,
        target: str,
        value: Any = None,
        path: tuple[str, ...] = (),
        permission_scope: str = "read",
    ) -> bool:
        visibility = self.visibility_for(key, value=value, path=path)
        target = str(target or "").lower()
        permission_scope = str(permission_scope or "read").lower()
        if visibility == ContextVisibility.SECRET:
            return False
        if target == "llm":
            return visibility == ContextVisibility.LLM_VISIBLE
        if target == "ui":
            return visibility in {ContextVisibility.LLM_VISIBLE, ContextVisibility.UI_VISIBLE}
        if target == "tool":
            if visibility == ContextVisibility.AUDIT_ONLY:
                return False
            if visibility == ContextVisibility.SYSTEM_ONLY:
                return permission_scope in {"system", "write", "admin"}
            return visibility in {ContextVisibility.LLM_VISIBLE, ContextVisibility.UI_VISIBLE, ContextVisibility.TOOL_ONLY}
        if target == "audit":
            return True
        return visibility == ContextVisibility.LLM_VISIBLE
