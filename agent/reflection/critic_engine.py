from __future__ import annotations

from pathlib import Path
from typing import Any

from .critic_policy import CriticPolicy
from .critic_sanitizer import CriticSanitizer
from .critic_types import (
    CriticAction,
    CriticIssue,
    CriticIssueCategory,
    CriticResult,
    CriticSeverity,
    CriticTargetType,
    CriticVerdict,
)
from .reflection_store import ReflectionStore


CERTAINTY_MARKERS = {
    "guaranteed",
    "must",
    "certain",
    "definitely",
    "will rise",
    "will fall",
    "已完成",
    "成功",
    "一定",
    "必然",
    "肯定",
    "会上涨",
    "会下跌",
}


class CriticEngine:
    def __init__(
        self,
        *,
        policy: CriticPolicy | None = None,
        sanitizer: CriticSanitizer | None = None,
        store: ReflectionStore | None = None,
        output_dir: str | Path = "outputs",
    ) -> None:
        self.policy = policy or CriticPolicy.default()
        self.sanitizer = sanitizer or CriticSanitizer(self.policy)
        self.store = store or ReflectionStore(output_dir=output_dir, sanitizer=self.sanitizer)

    def criticize_final_result(
        self,
        *,
        answer_summary: str,
        success: bool,
        result_status: str = "",
        tool_name: str = "",
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        target_ref: str = "",
        result_summary: dict[str, Any] | None = None,
        evidence_refs: list[dict[str, Any]] | None = None,
        observation_refs: list[dict[str, Any]] | None = None,
        replan_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
        memory_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
        risk_profile_summary: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CriticResult:
        safe_answer = str(self.sanitizer.sanitize_for_llm({"answer": answer_summary}).get("answer") or "")
        safe_summary = self.sanitizer.sanitize_for_context(result_summary or {})
        issues: list[CriticIssue] = []
        if self._contains_sensitive(answer_summary) or self._contains_sensitive(result_summary or {}):
            issues.append(
                self._issue(
                    CriticIssueCategory.SENSITIVE_DATA_EXPOSURE,
                    CriticSeverity.BLOCKING,
                    "Sensitive runtime fields were present in the final result candidate.",
                    target_type=CriticTargetType.FINAL_REPORT,
                )
            )
        if not success:
            issue_category = CriticIssueCategory.TOOL_FAILURE
            issue_severity = CriticSeverity.MEDIUM
            if self._has_certainty(answer_summary):
                issue_category = CriticIssueCategory.UNSUPPORTED_CLAIM
                issue_severity = CriticSeverity.HIGH
            issues.append(
                self._issue(
                    issue_category,
                    issue_severity,
                    "Final answer should reflect the failed or incomplete tool result.",
                    target_type=CriticTargetType.FINAL_REPORT,
                )
            )
        if self._requires_evidence(tool_name=tool_name, answer_summary=answer_summary) and not list(evidence_refs or []):
            issues.append(
                self._issue(
                    CriticIssueCategory.EVIDENCE_INSUFFICIENT,
                    CriticSeverity.MEDIUM,
                    "Market or news analysis answer has insufficient evidence refs.",
                    target_type=CriticTargetType.FINAL_REPORT,
                )
            )
        if self._looks_like_write_result(result_summary or {}) and not list(approval_refs or []):
            issues.append(
                self._issue(
                    CriticIssueCategory.WRITE_WITHOUT_APPROVAL,
                    CriticSeverity.HIGH,
                    "Write-like result lacks approval refs and must remain behind WriteGateway.",
                    target_type=CriticTargetType.PORTFOLIO_PROPOSAL,
                )
            )
        if risk_profile_summary and self._risk_conflict(risk_profile_summary):
            issues.append(
                self._issue(
                    CriticIssueCategory.RISK_PREFERENCE_CONFLICT,
                    CriticSeverity.MEDIUM,
                    "Risk summary indicates a possible mismatch with user risk constraints.",
                    target_type=CriticTargetType.RISK_ANALYSIS,
                )
            )
        return self._build_result(
            target_type=CriticTargetType.FINAL_REPORT,
            target_summary=safe_answer[:1200],
            target_ref=target_ref,
            issues=issues,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            evidence_refs=evidence_refs,
            observation_refs=observation_refs,
            replan_refs=replan_refs,
            message_refs=message_refs,
            memory_refs=memory_refs,
            approval_refs=approval_refs,
            metadata={
                "tool_name": str(tool_name or ""),
                "result_status": str(result_status or ""),
                "result_summary": safe_summary,
                **dict(metadata or {}),
            },
        )

    def criticize_tool_result_summary(
        self,
        *,
        result_summary: dict[str, Any],
        answer_summary: str = "",
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        tool_name: str = "",
        observation_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
    ) -> CriticResult:
        success = bool((result_summary or {}).get("success"))
        issues: list[CriticIssue] = []
        if not success and self._has_certainty(answer_summary):
            issues.append(
                self._issue(
                    CriticIssueCategory.UNSUPPORTED_CLAIM,
                    CriticSeverity.HIGH,
                    "Tool failed but answer summary sounds completed or certain.",
                    target_type=CriticTargetType.TOOL_RESULT,
                )
            )
        elif not success:
            issues.append(
                self._issue(
                    CriticIssueCategory.TOOL_FAILURE,
                    CriticSeverity.MEDIUM,
                    "Tool result is failed or incomplete.",
                    target_type=CriticTargetType.TOOL_RESULT,
                )
            )
        return self._build_result(
            target_type=CriticTargetType.TOOL_RESULT,
            target_summary=str((result_summary or {}).get("message") or answer_summary or tool_name)[:1200],
            issues=issues,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            observation_refs=observation_refs,
            message_refs=message_refs,
            metadata={"tool_name": str(tool_name or "")},
        )

    def criticize_portfolio_proposal(
        self,
        *,
        proposal_summary: dict[str, Any] | str,
        approval_refs: list[dict[str, Any]] | None = None,
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        observation_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
    ) -> CriticResult:
        issues: list[CriticIssue] = []
        if not list(approval_refs or []):
            issues.append(
                self._issue(
                    CriticIssueCategory.WRITE_WITHOUT_APPROVAL,
                    CriticSeverity.HIGH,
                    "Portfolio proposal must be routed through approval before commit.",
                    target_type=CriticTargetType.PORTFOLIO_PROPOSAL,
                )
            )
        return self._build_result(
            target_type=CriticTargetType.PORTFOLIO_PROPOSAL,
            target_summary=str(self.sanitizer.sanitize_for_llm({"proposal": proposal_summary}).get("proposal") or "")[:1200],
            issues=issues,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            observation_refs=observation_refs,
            message_refs=message_refs,
            approval_refs=approval_refs,
        )

    def criticize_risk_analysis(
        self,
        *,
        risk_summary: dict[str, Any] | str,
        evidence_refs: list[dict[str, Any]] | None = None,
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> CriticResult:
        issues: list[CriticIssue] = []
        encoded = str(risk_summary or "").lower()
        if any(marker in encoded for marker in ("high risk", "高风险", "concentration", "集中度")) and not list(evidence_refs or []):
            issues.append(
                self._issue(
                    CriticIssueCategory.RISK_POLICY_GAP,
                    CriticSeverity.HIGH,
                    "High-risk analysis lacks supporting refs.",
                    target_type=CriticTargetType.RISK_ANALYSIS,
                )
            )
        return self._build_result(
            target_type=CriticTargetType.RISK_ANALYSIS,
            target_summary=str(self.sanitizer.sanitize_for_llm({"risk": risk_summary}).get("risk") or "")[:1200],
            issues=issues,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            evidence_refs=evidence_refs,
        )

    def criticize_replan_decision(
        self,
        *,
        replan_summary: dict[str, Any] | str,
        observation_refs: list[dict[str, Any]] | None = None,
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
    ) -> CriticResult:
        issues: list[CriticIssue] = []
        if str(replan_summary or "").lower().find("requested") >= 0 and not list(observation_refs or []):
            issues.append(
                self._issue(
                    CriticIssueCategory.EVIDENCE_INSUFFICIENT,
                    CriticSeverity.MEDIUM,
                    "Replan decision should reference the observation that triggered it.",
                    target_type=CriticTargetType.REPLAN_DECISION,
                )
            )
        return self._build_result(
            target_type=CriticTargetType.REPLAN_DECISION,
            target_summary=str(self.sanitizer.sanitize_for_llm({"replan": replan_summary}).get("replan") or "")[:1200],
            issues=issues,
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            observation_refs=observation_refs,
        )

    def build_critic_context_from_refs(
        self,
        *,
        evidence_refs: list[dict[str, Any]] | None = None,
        observation_refs: list[dict[str, Any]] | None = None,
        replan_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
        memory_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        context = {
            "evidence_refs": list(evidence_refs or []),
            "observation_refs": list(observation_refs or []),
            "replan_refs": list(replan_refs or []),
            "message_refs": list(message_refs or []),
            "memory_refs": list(memory_refs or []),
            "approval_refs": list(approval_refs or []),
            "ref_counts": {
                "evidence": len(evidence_refs or []),
                "observation": len(observation_refs or []),
                "replan": len(replan_refs or []),
                "message": len(message_refs or []),
                "memory": len(memory_refs or []),
                "approval": len(approval_refs or []),
            },
        }
        return self.sanitizer.sanitize_for_context(context)

    def save_result(self, result: CriticResult, *, user_id: str = "default") -> dict[str, Any]:
        return self.store.save_result(result, user_id=user_id)

    def _build_result(
        self,
        *,
        target_type: CriticTargetType,
        target_summary: str,
        issues: list[CriticIssue],
        conversation_id: str = "",
        run_id: str = "",
        task_id: str = "",
        target_ref: str = "",
        evidence_refs: list[dict[str, Any]] | None = None,
        observation_refs: list[dict[str, Any]] | None = None,
        replan_refs: list[dict[str, Any]] | None = None,
        message_refs: list[dict[str, Any]] | None = None,
        memory_refs: list[dict[str, Any]] | None = None,
        approval_refs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CriticResult:
        action = self.policy.decide_action(issues)
        severity = _max_severity(issues)
        score = self.policy.score_result(issues)
        verdict = CriticVerdict.PASS
        if action == CriticAction.BLOCK_AND_REPORT:
            verdict = CriticVerdict.BLOCKED
        elif issues:
            verdict = CriticVerdict.WARNING if severity in {CriticSeverity.LOW, CriticSeverity.MEDIUM} else CriticVerdict.FAIL
        return CriticResult(
            conversation_id=conversation_id,
            run_id=run_id,
            task_id=task_id,
            target_type=target_type,
            target_ref=target_ref,
            target_summary=target_summary,
            verdict=verdict,
            action=action,
            severity=severity,
            score=score,
            issues=issues,
            evidence_refs=list(evidence_refs or []),
            observation_refs=list(observation_refs or []),
            replan_refs=list(replan_refs or []),
            message_refs=list(message_refs or []),
            memory_refs=list(memory_refs or []),
            approval_refs=list(approval_refs or []),
            revision_instruction=self._revision_instruction(action),
            replan_hint="Use existing read-only ReplanPolicy; do not auto-commit." if action == CriticAction.REPLAN_READONLY else "",
            handoff_hint="Record only; Phase 17 router will decide specialist routing." if action == CriticAction.HANDOFF_REQUESTED else "",
            requires_user_confirmation=action == CriticAction.REQUIRE_APPROVAL,
            metadata=self.sanitizer.sanitize_for_context(metadata or {}),
        )

    @staticmethod
    def _issue(
        category: CriticIssueCategory,
        severity: CriticSeverity,
        summary: str,
        *,
        target_type: CriticTargetType,
    ) -> CriticIssue:
        return CriticIssue(
            category=category,
            severity=severity,
            target_type=target_type,
            summary=summary,
        )

    @staticmethod
    def _revision_instruction(action: CriticAction) -> str:
        if action == CriticAction.REVISE_ANSWER:
            return "Revise only the final wording; do not change business data or write state."
        if action == CriticAction.ASK_USER:
            return "Ask the user for the missing required information."
        if action == CriticAction.REQUIRE_APPROVAL:
            return "Keep the operation behind WriteGateway approval and revalidate before commit."
        if action == CriticAction.BLOCK_AND_REPORT:
            return "Block unsafe output and report a safe summary."
        return ""

    @staticmethod
    def _contains_sensitive(value: Any) -> bool:
        encoded = str(value or "").lower()
        return any(
            marker in encoded
            for marker in (
                "confirmation_token",
                "api_key",
                "tushare_token",
                "password",
                "authorization",
                "agent_quant.db",
                "raw_positions",
                "raw_evidence",
                "raw_tool_payload",
                "traceback",
                "stack_trace",
                ":\\",
                "\\users\\",
            )
        )

    @staticmethod
    def _has_certainty(text: str) -> bool:
        lowered = str(text or "").lower()
        return any(marker in lowered for marker in CERTAINTY_MARKERS)

    @staticmethod
    def _requires_evidence(*, tool_name: str, answer_summary: str) -> bool:
        lowered = f"{tool_name} {answer_summary}".lower()
        return any(marker in lowered for marker in ("stock_news", "stock_rag", "rag", "news", "公告", "新闻", "证据"))

    @staticmethod
    def _looks_like_write_result(result_summary: dict[str, Any]) -> bool:
        """Detect write/proposal state only from structured fields.

        Natural-language words such as "Commit", "paper trading" or "not executed"
        are explanations and must never trigger an approval requirement.
        """
        write_operation_types = {"proposal", "preview", "write", "commit"}
        write_tool_names = {
            "approval.confirm_plan",
            "portfolio.commit_paper_trade",
            "portfolio.preview_manual_change",
            "portfolio.preview_rebalance",
            "portfolio.preview_adjust_position",
            "portfolio.preview_paper_trade",
            "capital.change.preview",
            "capital.change.commit",
            "backfill.preview",
            "backfill.commit",
            "strategy.management.preview",
            "strategy.disable.preview",
            "strategy.disable.commit",
        }

        def visit(value: Any, depth: int = 0) -> bool:
            if depth > 8:
                return False
            if isinstance(value, dict):
                operation_type = str(value.get("operation_type") or "").strip().lower()
                if operation_type in write_operation_types:
                    return True
                if value.get("requires_confirmation") is True or value.get("write_requested") is True:
                    return True
                if any(str(value.get(key) or "").strip() for key in ("plan_id", "pending_plan_id", "commit_id")):
                    return True
                commit_status = str(value.get("commit_status") or "").strip().lower()
                if commit_status and commit_status not in {"not_committed", "none", "not_executed"}:
                    return True
                tool_name = str(value.get("tool_name") or value.get("canonical_tool_name") or "").strip()
                if tool_name in write_tool_names:
                    return True
                return any(visit(item, depth + 1) for item in value.values())
            if isinstance(value, (list, tuple)):
                return any(visit(item, depth + 1) for item in value)
            return False

        return visit(dict(result_summary or {}))

    @staticmethod
    def _risk_conflict(risk_summary: dict[str, Any]) -> bool:
        encoded = str(risk_summary or "").lower()
        return "risk_preference_conflict" in encoded or "风险偏好冲突" in encoded


def _max_severity(issues: list[CriticIssue]) -> CriticSeverity:
    order = {
        CriticSeverity.INFO: 0,
        CriticSeverity.LOW: 1,
        CriticSeverity.MEDIUM: 2,
        CriticSeverity.HIGH: 3,
        CriticSeverity.BLOCKING: 4,
    }
    if not issues:
        return CriticSeverity.INFO
    return max((issue.severity for issue in issues), key=lambda item: order.get(item, 0))
