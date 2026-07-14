from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .critic_types import (
    CriticAction,
    CriticIssue,
    CriticIssueCategory,
    CriticResult,
    CriticSeverity,
)


class CriticVisibility(str, Enum):
    LLM_VISIBLE = "LLM_VISIBLE"
    UI_VISIBLE = "UI_VISIBLE"
    TOOL_ONLY = "TOOL_ONLY"
    SYSTEM_ONLY = "SYSTEM_ONLY"
    AUDIT_ONLY = "AUDIT_ONLY"
    SECRET = "SECRET"


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
    "chain_of_thought",
    "internal_stack",
    "private_chain_of_thought",
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
    "action",
    "approval_refs",
    "artifact_id",
    "category",
    "context_id",
    "conversation_id",
    "created_at",
    "critic_id",
    "evidence_refs",
    "handoff_hint",
    "issue_count",
    "issue_id",
    "memory_refs",
    "message_refs",
    "observation_refs",
    "replan_refs",
    "requires_user_confirmation",
    "revision_instruction",
    "replan_hint",
    "run_id",
    "score",
    "severity",
    "source_refs",
    "status",
    "summary",
    "target_ref",
    "target_summary",
    "target_type",
    "task_id",
    "tool_call_id",
    "verdict",
}

SEVERITY_WEIGHT = {
    CriticSeverity.INFO: 0.0,
    CriticSeverity.LOW: 0.08,
    CriticSeverity.MEDIUM: 0.18,
    CriticSeverity.HIGH: 0.35,
    CriticSeverity.BLOCKING: 0.6,
}


@dataclass(frozen=True)
class CriticPolicy:
    default_visibility: CriticVisibility = CriticVisibility.LLM_VISIBLE
    secret_keys: set[str] = field(default_factory=lambda: set(SECRET_KEYS))
    system_only_keys: set[str] = field(default_factory=lambda: set(SYSTEM_ONLY_KEYS))
    audit_only_keys: set[str] = field(default_factory=lambda: set(AUDIT_ONLY_KEYS))
    tool_only_keys: set[str] = field(default_factory=lambda: set(TOOL_ONLY_KEYS))
    llm_visible_keys: set[str] = field(default_factory=lambda: set(LLM_VISIBLE_KEYS))

    @classmethod
    def default(cls) -> "CriticPolicy":
        return cls()

    def classify_field(
        self,
        key: str,
        value: Any = None,
        path: tuple[str, ...] = (),
    ) -> CriticVisibility:
        del value
        lowered = str(key or "").lower()
        joined = ".".join([*path, lowered]).lower()
        if lowered == "token_present":
            return CriticVisibility.LLM_VISIBLE
        if lowered in self.secret_keys or any(marker in lowered for marker in ("api_key", "password", "secret")):
            return CriticVisibility.SECRET
        if "confirmation_token" in lowered or lowered == "tushare_token":
            return CriticVisibility.SECRET
        if lowered in self.audit_only_keys or any(marker in joined for marker in ("traceback", "stack_trace", "internal_stack", "chain_of_thought")):
            return CriticVisibility.AUDIT_ONLY
        if lowered in self.system_only_keys:
            return CriticVisibility.SYSTEM_ONLY
        if (
            lowered in self.tool_only_keys
            or joined.endswith(".raw_evidence")
            or joined.endswith(".raw_positions")
            or joined.endswith(".raw_tool_payload")
        ):
            return CriticVisibility.TOOL_ONLY
        if lowered in self.llm_visible_keys:
            return CriticVisibility.LLM_VISIBLE
        return self.default_visibility

    def classify_issue(self, value: CriticIssue | dict[str, Any] | str) -> CriticIssueCategory:
        if isinstance(value, CriticIssue):
            return value.category
        if isinstance(value, dict) and value.get("category"):
            return CriticIssueCategory.from_value(value.get("category"))

        haystack = _issue_text(value)
        if any(marker in haystack for marker in ("confirmation_token", "api_key", "tushare_token", "password", "secret", "traceback", "raw_payload", "raw_tool_payload")):
            return CriticIssueCategory.SENSITIVE_DATA_EXPOSURE
        if any(marker in haystack for marker in ("write", "commit", "paper_trade", "portfolio", "approval", "confirm")) and any(
            marker in haystack for marker in ("missing", "without", "not approved", "unapproved", "未确认", "未审批")
        ):
            return CriticIssueCategory.WRITE_WITHOUT_APPROVAL
        if any(marker in haystack for marker in ("permission", "denied", "blocked", "forbidden", "权限")):
            return CriticIssueCategory.PERMISSION_BLOCKED
        if any(marker in haystack for marker in ("evidence", "context", "source", "unsupported", "insufficient", "no source", "证据不足")):
            return CriticIssueCategory.EVIDENCE_INSUFFICIENT
        if any(marker in haystack for marker in ("missing user", "missing parameter", "ask user", "clarification", "缺少用户", "需要用户")):
            return CriticIssueCategory.MISSING_USER_INFO
        if any(marker in haystack for marker in ("tool failed", "tool error", "exception", "failed", "失败")):
            return CriticIssueCategory.TOOL_FAILURE
        if any(marker in haystack for marker in ("empty", "no result", "空结果", "无结果")):
            return CriticIssueCategory.EMPTY_RESULT
        if any(marker in haystack for marker in ("risk preference", "风险偏好", "不匹配")):
            return CriticIssueCategory.RISK_PREFERENCE_CONFLICT
        if any(marker in haystack for marker in ("concentration", "high risk", "risk rule", "一手", "集中度")):
            return CriticIssueCategory.RISK_POLICY_GAP
        if "handoff" in haystack:
            return CriticIssueCategory.HANDOFF_NEEDED
        return CriticIssueCategory.UNKNOWN

    def score_result(self, result: CriticResult | dict[str, Any] | list[CriticIssue | dict[str, Any]]) -> float:
        if isinstance(result, CriticResult):
            issues = list(result.issues or [])
        elif isinstance(result, dict):
            issues = [
                issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(dict(issue or {}))
                for issue in (result.get("issues") or [])
            ]
        else:
            issues = [
                issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(dict(issue or {}))
                for issue in (result or [])
            ]
        penalty = sum(SEVERITY_WEIGHT.get(issue.severity, 0.1) for issue in issues)
        return max(0.0, min(1.0, round(1.0 - penalty, 4)))

    def decide_action(self, result_or_issues: CriticResult | dict[str, Any] | list[CriticIssue | dict[str, Any]]) -> CriticAction:
        issues = self._coerce_issues(result_or_issues)
        categories = {issue.category for issue in issues}
        severities = {issue.severity for issue in issues}
        if not issues:
            return CriticAction.PASS
        if CriticIssueCategory.SENSITIVE_DATA_EXPOSURE in categories:
            return CriticAction.BLOCK_AND_REPORT
        if CriticIssueCategory.PERMISSION_BLOCKED in categories:
            return CriticAction.BLOCK_AND_REPORT
        if CriticIssueCategory.WRITE_WITHOUT_APPROVAL in categories:
            return CriticAction.REQUIRE_APPROVAL if CriticSeverity.BLOCKING not in severities else CriticAction.BLOCK_AND_REPORT
        if CriticIssueCategory.MISSING_USER_INFO in categories:
            return CriticAction.ASK_USER
        if CriticIssueCategory.HANDOFF_NEEDED in categories:
            return CriticAction.HANDOFF_REQUESTED
        if categories & {CriticIssueCategory.EVIDENCE_INSUFFICIENT, CriticIssueCategory.EMPTY_RESULT, CriticIssueCategory.TOOL_FAILURE}:
            return CriticAction.REPLAN_READONLY
        if CriticIssueCategory.RISK_POLICY_GAP in categories and severities & {CriticSeverity.HIGH, CriticSeverity.BLOCKING}:
            return CriticAction.REQUIRE_APPROVAL
        if categories & {
            CriticIssueCategory.RISK_POLICY_GAP,
            CriticIssueCategory.RISK_PREFERENCE_CONFLICT,
            CriticIssueCategory.UNSUPPORTED_CLAIM,
            CriticIssueCategory.FORMAT_OR_DISCLAIMER_GAP,
        }:
            return CriticAction.REVISE_ANSWER
        return CriticAction.REVISE_ANSWER

    def can_deliver(self, visibility: CriticVisibility | str, target: str, *, permission_scope: str = "read") -> bool:
        if not isinstance(visibility, CriticVisibility):
            visibility = CriticVisibility(str(visibility))
        target = str(target or "").lower()
        permission_scope = str(permission_scope or "read").lower()
        if visibility == CriticVisibility.SECRET:
            return False
        if target == "llm":
            return visibility == CriticVisibility.LLM_VISIBLE
        if target == "ui":
            return visibility in {CriticVisibility.LLM_VISIBLE, CriticVisibility.UI_VISIBLE}
        if target == "context":
            return visibility == CriticVisibility.LLM_VISIBLE
        if target == "tool":
            if visibility == CriticVisibility.AUDIT_ONLY:
                return False
            if visibility == CriticVisibility.SYSTEM_ONLY:
                return permission_scope in {"admin", "system", "write"}
            return visibility in {CriticVisibility.LLM_VISIBLE, CriticVisibility.UI_VISIBLE, CriticVisibility.TOOL_ONLY}
        if target in {"audit", "system", "internal"}:
            return visibility != CriticVisibility.SECRET
        return visibility == CriticVisibility.LLM_VISIBLE

    def can_show_to_llm(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "llm")

    def can_show_to_ui(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.can_deliver(self.classify_field(key, value=value, path=path), "ui")

    def requires_redaction(self, key: str, value: Any = None, path: tuple[str, ...] = ()) -> bool:
        return self.classify_field(key, value=value, path=path) in {
            CriticVisibility.SECRET,
            CriticVisibility.SYSTEM_ONLY,
            CriticVisibility.AUDIT_ONLY,
            CriticVisibility.TOOL_ONLY,
        }

    @staticmethod
    def _coerce_issues(result_or_issues: CriticResult | dict[str, Any] | list[CriticIssue | dict[str, Any]]) -> list[CriticIssue]:
        if isinstance(result_or_issues, CriticResult):
            return list(result_or_issues.issues or [])
        if isinstance(result_or_issues, dict):
            return [
                issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(dict(issue or {}))
                for issue in (result_or_issues.get("issues") or [])
            ]
        return [
            issue if isinstance(issue, CriticIssue) else CriticIssue.from_dict(dict(issue or {}))
            for issue in (result_or_issues or [])
        ]


def _issue_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(item).lower() for item in value.values())
    return str(value or "").lower()
