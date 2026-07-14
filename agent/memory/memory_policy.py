from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .memory_types import MemoryRecord, MemoryType, MemoryVisibility


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

RAW_OBJECT_KEYS = {
    "complete_payload",
    "full_payload",
    "full_result",
    "raw_evidence",
    "raw_payload",
    "raw_positions",
    "raw_tool_payload",
}

SAFE_APPROVAL_KEYS = {
    "operation_type",
    "plan_hash",
    "plan_id",
    "proposal_summary",
    "status",
    "summary",
    "token_present",
}

LLM_VISIBLE_KEYS = {
    "answer",
    "artifact_id",
    "artifact_refs",
    "confidence",
    "content",
    "conversation_id",
    "created_at",
    "evidence_summary",
    "importance",
    "memory_id",
    "memory_type",
    "message_id",
    "plan_id",
    "portfolio_summary",
    "refs",
    "run_id",
    "source_id",
    "source_refs",
    "source_type",
    "status",
    "stock_codes",
    "summary",
    "task_id",
    "token_present",
    "topics",
    "user_id",
}

USER_FACT_SUBTYPES = {
    "investment_goal",
    "language_preference",
    "long_term_preference",
    "preference",
    "profile",
    "risk_preference",
    "stable_constraint",
}

CONFIRMED_USER_SOURCES = {
    "confirmed_user_preference",
    "manual_import",
    "profile_setting",
    "user_feedback",
}

ONE_TIME_MARKERS = {
    "action_proposal",
    "confirm_execute",
    "manual_position_operation",
    "one_time",
    "one_time_position_operation",
    "trade_preview",
}


@dataclass(frozen=True)
class MemoryPolicy:
    default_visibility: MemoryVisibility = MemoryVisibility.LLM_VISIBLE
    secret_keys: set[str] = field(default_factory=lambda: set(SECRET_KEYS))
    system_only_keys: set[str] = field(default_factory=lambda: set(SYSTEM_ONLY_KEYS))
    audit_only_keys: set[str] = field(default_factory=lambda: set(AUDIT_ONLY_KEYS))
    raw_object_keys: set[str] = field(default_factory=lambda: set(RAW_OBJECT_KEYS))
    llm_visible_keys: set[str] = field(default_factory=lambda: set(LLM_VISIBLE_KEYS))

    @classmethod
    def default(cls) -> "MemoryPolicy":
        return cls()

    def classify_field(
        self,
        key: str,
        value: Any = None,
        path: tuple[str, ...] = (),
    ) -> MemoryVisibility:
        del value
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered == "token_present":
            return MemoryVisibility.LLM_VISIBLE
        if lowered in self.secret_keys or any(marker in lowered for marker in ("api_key", "password", "secret")):
            return MemoryVisibility.SECRET
        if "confirmation_token" in lowered or lowered == "tushare_token":
            return MemoryVisibility.SECRET
        if lowered in self.audit_only_keys or any(marker in joined for marker in ("traceback", "stack_trace", "internal_stack")):
            return MemoryVisibility.AUDIT_ONLY
        if lowered in self.system_only_keys:
            return MemoryVisibility.SYSTEM_ONLY
        if lowered in self.raw_object_keys or joined.endswith(".raw_evidence") or joined.endswith(".raw_positions"):
            return MemoryVisibility.TOOL_ONLY
        if lowered in self.llm_visible_keys:
            return MemoryVisibility.LLM_VISIBLE
        return self.default_visibility

    def can_deliver(self, visibility: MemoryVisibility | str, target: str, *, permission_scope: str = "read") -> bool:
        if not isinstance(visibility, MemoryVisibility):
            visibility = MemoryVisibility.from_value(visibility)
        target = str(target or "").lower()
        permission_scope = str(permission_scope or "read").lower()
        if visibility == MemoryVisibility.SECRET:
            return False
        if target == "llm":
            return visibility == MemoryVisibility.LLM_VISIBLE
        if target == "ui":
            return visibility in {MemoryVisibility.LLM_VISIBLE, MemoryVisibility.UI_VISIBLE}
        if target == "tool":
            if visibility == MemoryVisibility.AUDIT_ONLY:
                return False
            if visibility == MemoryVisibility.SYSTEM_ONLY:
                return permission_scope in {"admin", "system", "write"}
            return visibility in {
                MemoryVisibility.LLM_VISIBLE,
                MemoryVisibility.UI_VISIBLE,
                MemoryVisibility.TOOL_ONLY,
            }
        if target in {"audit", "system", "internal"}:
            return visibility != MemoryVisibility.SECRET
        return visibility == MemoryVisibility.LLM_VISIBLE

    def can_show_to_llm(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "llm")

    def can_show_to_ui(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "ui")

    def can_store_field(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        visibility = self.classify_field(key, value=value, path=path)
        return visibility in {MemoryVisibility.LLM_VISIBLE, MemoryVisibility.UI_VISIBLE}

    def requires_user_confirmation(self, record: MemoryRecord | dict[str, Any]) -> bool:
        record = record if isinstance(record, MemoryRecord) else MemoryRecord.from_dict(record)
        subtype = _record_subtype(record)
        category = str(record.metadata.get("category") or record.metadata.get("memory_category") or "").lower()
        return record.memory_type == MemoryType.SEMANTIC and (
            subtype in USER_FACT_SUBTYPES or category in {"profile", "user_fact", "user_preference"}
        )

    def validate_record(self, record: MemoryRecord | dict[str, Any]) -> list[str]:
        record = record if isinstance(record, MemoryRecord) else MemoryRecord.from_dict(record)
        issues: list[str] = []
        if self.requires_user_confirmation(record) and not _is_user_confirmed(record):
            issues.append("long_term_user_fact_requires_confirmation")
        if _has_one_time_marker(record):
            issues.append("one_time_operation_cannot_be_long_term_memory")
        if _value_has_forbidden_text(record.content) or _value_has_forbidden_text(record.summary):
            issues.append("memory_text_contains_forbidden_sensitive_content")
        for path, key, value in _walk_fields(record.metadata):
            if not self.can_store_field(key, value=value, path=path):
                issues.append(f"metadata_field_not_storable:{'.'.join([*path, key])}")
        for ref_name in ("context_refs", "message_refs", "artifact_refs", "approval_refs", "source_refs"):
            for path, key, value in _walk_fields(getattr(record, ref_name)):
                if not self.can_store_field(key, value=value, path=(ref_name, *path)):
                    issues.append(f"{ref_name}_field_not_storable:{'.'.join([*path, key])}")
        if _is_approval_record(record):
            for key in record.metadata:
                if key not in SAFE_APPROVAL_KEYS and key not in {"category", "layer", "version"}:
                    if not self.can_store_field(key, record.metadata.get(key)):
                        continue
                    issues.append(f"approval_memory_unsupported_field:{key}")
        return sorted(set(issues))

    def allow_store(self, record: MemoryRecord | dict[str, Any]) -> tuple[bool, list[str]]:
        issues = self.validate_record(record)
        return not issues, issues

    def assert_can_store(self, record: MemoryRecord | dict[str, Any]) -> None:
        allowed, issues = self.allow_store(record)
        if not allowed:
            raise ValueError(";".join(issues))


def _record_subtype(record: MemoryRecord) -> str:
    subtype = record.memory_subtype or record.metadata.get("memory_type")
    protocol = record.metadata.get("protocol")
    if isinstance(protocol, dict):
        subtype = subtype or protocol.get("memory_type")
    return str(subtype or "").lower()


def _is_user_confirmed(record: MemoryRecord) -> bool:
    source = str(record.source_type or "").lower()
    if source in CONFIRMED_USER_SOURCES:
        return True
    protocol = record.metadata.get("protocol")
    protocol_confirmed = protocol.get("user_confirmed") if isinstance(protocol, dict) else False
    return bool(record.metadata.get("user_confirmed") or protocol_confirmed)


def _has_one_time_marker(record: MemoryRecord) -> bool:
    subtype = _record_subtype(record)
    source = str(record.source_type or "").lower()
    operation_scope = str(record.metadata.get("operation_scope") or "").lower()
    return subtype in ONE_TIME_MARKERS or source in ONE_TIME_MARKERS or operation_scope in ONE_TIME_MARKERS


def _is_approval_record(record: MemoryRecord) -> bool:
    source = str(record.source_type or "").lower()
    category = str(record.metadata.get("category") or "").lower()
    return source in {"action_approval", "action_proposal", "pending_plan"} or category in {"approval", "pending_plan"}


def _walk_fields(value: Any, path: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[tuple[str, ...], str, Any]] = []
        for key, item in value.items():
            key_text = str(key)
            items.append((path, key_text, item))
            items.extend(_walk_fields(item, (*path, key_text)))
        return items
    if isinstance(value, list):
        items = []
        for index, item in enumerate(value):
            items.extend(_walk_fields(item, (*path, str(index))))
        return items
    return []


def _value_has_forbidden_text(value: Any) -> bool:
    text = str(value or "").lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "agent_quant.db",
            "api_key",
            "confirmation_token",
            "traceback (most recent call last)",
            "tushare_token",
        )
    ) or ":\\" in str(value or "")
