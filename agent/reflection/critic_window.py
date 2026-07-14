from __future__ import annotations

import json
from typing import Any

from .critic_policy import CriticPolicy
from .critic_sanitizer import CriticSanitizer
from .critic_types import (
    CriticAction,
    CriticIssue,
    CriticResult,
    CriticSeverity,
    CriticSummary,
)


BLOCKING_ACTIONS = {
    CriticAction.ASK_USER,
    CriticAction.REQUIRE_APPROVAL,
    CriticAction.BLOCK_AND_REPORT,
}


class CriticWindow:
    def __init__(
        self,
        *,
        default_budget: int = 6000,
        policy: CriticPolicy | None = None,
        sanitizer: CriticSanitizer | None = None,
    ) -> None:
        self.default_budget = int(default_budget or 6000)
        self.policy = policy or CriticPolicy.default()
        self.sanitizer = sanitizer or CriticSanitizer(self.policy)

    def trim_critic_results_to_budget(
        self,
        results: list[CriticResult | dict[str, Any]],
        *,
        budget: int | None = None,
        target: str = "llm",
    ) -> list[dict[str, Any]]:
        max_budget = int(budget or self.default_budget)
        normalized = [self._coerce(item) for item in results or []]
        required = [item for item in normalized if self._is_blocking(item)]
        recent = [item for item in normalized if item not in required]
        kept: list[dict[str, Any]] = []
        used = 0

        for item in [*required, *reversed(recent)]:
            safe = self._sanitize(item, target=target)
            size = self.estimate_critic_size(safe)
            if used + size <= max_budget or self._is_blocking(item):
                kept.append(safe)
                used += size
                continue
            summary = self.summarize_old_critic_results([item])[0].to_dict()
            size = self.estimate_critic_size(summary)
            if used + size <= max_budget:
                kept.append(summary)
                used += size
        return sorted(kept, key=lambda row: str(row.get("created_at") or row.get("critic_id") or ""))

    def summarize_old_critic_results(
        self,
        results: list[CriticResult | dict[str, Any]],
    ) -> list[CriticSummary]:
        summaries: list[CriticSummary] = []
        for raw in results or []:
            item = self._coerce(raw)
            safe = self.sanitizer.sanitize_for_context(item)
            summaries.append(
                CriticSummary(
                    critic_id=str(safe.get("critic_id") or item.critic_id),
                    target_type=item.target_type,
                    action=item.action,
                    severity=item.severity,
                    score=item.score,
                    issue_count=len(item.issues or []),
                    summary=str(safe.get("target_summary") or item.target_summary or item.action.value),
                    evidence_refs=list(safe.get("evidence_refs") or []),
                    observation_refs=list(safe.get("observation_refs") or []),
                    replan_refs=list(safe.get("replan_refs") or []),
                    message_refs=list(safe.get("message_refs") or []),
                    approval_refs=list(safe.get("approval_refs") or []),
                    blocking=self._is_blocking(item),
                )
            )
        return summaries

    def keep_blocking_issues(
        self,
        results: list[CriticResult | dict[str, Any]],
        *,
        target: str = "context",
    ) -> list[dict[str, Any]]:
        blocking: list[dict[str, Any]] = []
        for raw in results or []:
            item = self._coerce(raw)
            kept_issues = [issue for issue in item.issues if self._is_blocking_issue(issue)]
            if kept_issues or self._is_blocking(item):
                clone = CriticResult.from_dict(item.to_dict())
                clone.issues = kept_issues or clone.issues
                blocking.append(self._sanitize(clone, target=target))
        return blocking

    @staticmethod
    def estimate_critic_size(result: CriticResult | dict[str, Any]) -> int:
        value = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))

    def _sanitize(self, result: CriticResult, *, target: str) -> dict[str, Any]:
        if target == "ui":
            return self.sanitizer.sanitize_for_ui(result)
        if target == "context":
            return self.sanitizer.sanitize_for_context(result)
        if target == "audit":
            return self.sanitizer.sanitize_for_audit(result)
        return self.sanitizer.sanitize_for_llm(result)

    @staticmethod
    def _coerce(result: CriticResult | dict[str, Any]) -> CriticResult:
        return result if isinstance(result, CriticResult) else CriticResult.from_dict(dict(result or {}))

    @staticmethod
    def _is_blocking(result: CriticResult) -> bool:
        return (
            result.action in BLOCKING_ACTIONS
            or result.severity == CriticSeverity.BLOCKING
            or any(CriticWindow._is_blocking_issue(issue) for issue in result.issues or [])
        )

    @staticmethod
    def _is_blocking_issue(issue: CriticIssue) -> bool:
        return issue.severity in {CriticSeverity.HIGH, CriticSeverity.BLOCKING}
