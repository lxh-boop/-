from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .observation_types import ObservationEvent, ObservationSeverity, ObservationType
from .observe_policy import ObservePolicy
from .replan_types import (
    ReplanDecision,
    ReplanDecisionStatus,
    ReplanReason,
    ReplanScope,
)


REASON_BY_OBSERVATION = {
    ObservationType.CONTEXT_INSUFFICIENT: ReplanReason.MISSING_REQUIRED_CONTEXT,
    ObservationType.TOOL_EMPTY_RESULT: ReplanReason.TOOL_RESULT_EMPTY,
    ObservationType.EVIDENCE_INSUFFICIENT: ReplanReason.EVIDENCE_INSUFFICIENT,
    ObservationType.MEMORY_EMPTY: ReplanReason.MEMORY_INSUFFICIENT,
    ObservationType.TOOL_PERMISSION_BLOCKED: ReplanReason.PERMISSION_BLOCKED,
    ObservationType.APPROVAL_REQUIRED: ReplanReason.APPROVAL_REQUIRED,
    ObservationType.APPROVAL_DENIED: ReplanReason.APPROVAL_DENIED,
    ObservationType.USER_CLARIFICATION_NEEDED: ReplanReason.MISSING_REQUIRED_PARAMETER,
    ObservationType.TASK_FAILED: ReplanReason.TASK_DEPENDENCY_FAILED,
    ObservationType.TASK_PARTIAL_SUCCESS: ReplanReason.TASK_DEPENDENCY_FAILED,
}


SCOPE_BY_REASON = {
    ReplanReason.MISSING_REQUIRED_CONTEXT: ReplanScope.DEPENDENT_TASKS,
    ReplanReason.MISSING_REQUIRED_PARAMETER: ReplanScope.ASK_USER_CLARIFICATION,
    ReplanReason.TOOL_ERROR_RECOVERABLE: ReplanScope.CURRENT_TASK,
    ReplanReason.TOOL_ERROR_BLOCKING: ReplanScope.BLOCK_AND_REPORT,
    ReplanReason.TOOL_RESULT_EMPTY: ReplanScope.CURRENT_TASK,
    ReplanReason.EVIDENCE_INSUFFICIENT: ReplanScope.DEPENDENT_TASKS,
    ReplanReason.MEMORY_INSUFFICIENT: ReplanScope.CURRENT_TASK,
    ReplanReason.PERMISSION_BLOCKED: ReplanScope.BLOCK_AND_REPORT,
    ReplanReason.APPROVAL_REQUIRED: ReplanScope.PLAN_SUMMARY_ONLY,
    ReplanReason.APPROVAL_DENIED: ReplanScope.BLOCK_AND_REPORT,
    ReplanReason.USER_GOAL_CHANGED: ReplanScope.DEPENDENT_TASKS,
    ReplanReason.TASK_DEPENDENCY_FAILED: ReplanScope.DEPENDENT_TASKS,
    ReplanReason.MAX_CONTEXT_BUDGET_EXCEEDED: ReplanScope.PLAN_SUMMARY_ONLY,
    ReplanReason.MAX_REPLAN_LIMIT_REACHED: ReplanScope.BLOCK_AND_REPORT,
}


@dataclass
class ReplanLimiter:
    max_run_replans: int = 2
    max_task_replans: int = 1
    max_same_reason: int = 1
    run_counts: dict[str, int] = field(default_factory=dict)
    task_counts: dict[str, int] = field(default_factory=dict)
    reason_counts: dict[str, int] = field(default_factory=dict)

    def can_replan(self, *, run_id: str, task_id: str = "", reason: ReplanReason | str = "") -> tuple[bool, list[str]]:
        run_id = str(run_id or "no_run")
        task_id = str(task_id or "no_task")
        reason_text = ReplanReason.from_value(reason).value if reason else ""
        blocked: list[str] = []
        if self.run_counts.get(run_id, 0) >= self.max_run_replans:
            blocked.append("max_run_replans_reached")
        if task_id and self.task_counts.get(f"{run_id}:{task_id}", 0) >= self.max_task_replans:
            blocked.append("max_task_replans_reached")
        if reason_text and self.reason_counts.get(f"{run_id}:{task_id}:{reason_text}", 0) >= self.max_same_reason:
            blocked.append("same_reason_replan_limit_reached")
        return not blocked, blocked

    def record(self, *, run_id: str, task_id: str = "", reason: ReplanReason | str = "") -> None:
        run_id = str(run_id or "no_run")
        task_id = str(task_id or "no_task")
        reason_text = ReplanReason.from_value(reason).value if reason else ""
        self.run_counts[run_id] = self.run_counts.get(run_id, 0) + 1
        self.task_counts[f"{run_id}:{task_id}"] = self.task_counts.get(f"{run_id}:{task_id}", 0) + 1
        if reason_text:
            key = f"{run_id}:{task_id}:{reason_text}"
            self.reason_counts[key] = self.reason_counts.get(key, 0) + 1


class ReplanPolicy:
    def __init__(self, *, observe_policy: ObservePolicy | None = None, limiter: ReplanLimiter | None = None) -> None:
        self.observe_policy = observe_policy or ObservePolicy.default()
        self.limiter = limiter or ReplanLimiter()

    def evaluate_observation(self, observation: ObservationEvent | dict[str, Any]) -> dict[str, Any]:
        event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
        reason = self._reason_for_event(event)
        scope = SCOPE_BY_REASON.get(reason, ReplanScope.NO_REPLAN)
        should = self.should_replan(event)
        return {
            "should_replan": should,
            "reason": reason.value,
            "scope": scope.value,
            "summary": self.summarize_replan_reason(reason),
        }

    def should_replan(self, observation: ObservationEvent | dict[str, Any]) -> bool:
        event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
        if event.observation_type == ObservationType.APPROVAL_REQUIRED:
            return True
        if event.observation_type in {ObservationType.TOOL_SUCCESS, ObservationType.REPORT_READY, ObservationType.MEMORY_HIT}:
            return False
        return self.observe_policy.requires_replan_check(event)

    def build_replan_decision(
        self,
        observation: ObservationEvent | dict[str, Any],
        *,
        record: bool = False,
    ) -> ReplanDecision:
        event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
        reason = self._reason_for_event(event)
        scope = SCOPE_BY_REASON.get(reason, ReplanScope.NO_REPLAN)
        should = self.should_replan(event)
        allowed, blocked_by = self.check_replan_limit(event, reason=reason)
        status = ReplanDecisionStatus.SKIPPED
        if event.observation_type == ObservationType.APPROVAL_REQUIRED:
            status = ReplanDecisionStatus.WAIT_APPROVAL
            blocked_by = list(dict.fromkeys([*blocked_by, "write_gateway_required"]))
        elif event.observation_type == ObservationType.TOOL_PERMISSION_BLOCKED:
            status = ReplanDecisionStatus.BLOCKED
            blocked_by = list(dict.fromkeys([*blocked_by, "permission_escalation_disallowed"]))
        elif not should:
            status = ReplanDecisionStatus.SKIPPED
            scope = ReplanScope.NO_REPLAN
        elif not allowed:
            status = ReplanDecisionStatus.BLOCKED
            reason = ReplanReason.MAX_REPLAN_LIMIT_REACHED
            scope = ReplanScope.BLOCK_AND_REPORT
        elif scope in {ReplanScope.BLOCK_AND_REPORT, ReplanScope.ASK_USER_CLARIFICATION}:
            status = ReplanDecisionStatus.BLOCKED
        else:
            status = ReplanDecisionStatus.REQUESTED
            if record:
                self.limiter.record(run_id=event.run_id, task_id=event.task_id, reason=reason)
        return ReplanDecision(
            conversation_id=event.conversation_id,
            run_id=event.run_id,
            task_id=event.task_id,
            trigger_observation_id=event.observation_id,
            reason=reason,
            scope=scope,
            status=status,
            summary=self.summarize_replan_reason(reason),
            suggested_plan_patch=self._suggested_patch(reason, event),
            blocked_by=blocked_by,
            observation_refs=[{"observation_id": event.observation_id, "observation_type": event.observation_type.value}],
            context_refs=list(event.context_refs or []),
            artifact_refs=list(event.artifact_refs or []),
            metadata={
                "auto_commit": False,
                "requires_write_gateway": event.observation_type == ObservationType.APPROVAL_REQUIRED,
                "permission_escalation_allowed": False,
            },
        )

    def check_replan_limit(
        self,
        observation: ObservationEvent | dict[str, Any],
        *,
        reason: ReplanReason | str | None = None,
    ) -> tuple[bool, list[str]]:
        event = observation if isinstance(observation, ObservationEvent) else ObservationEvent.from_dict(dict(observation or {}))
        return self.limiter.can_replan(
            run_id=event.run_id,
            task_id=event.task_id,
            reason=reason or self._reason_for_event(event),
        )

    @staticmethod
    def summarize_replan_reason(reason: ReplanReason | str) -> str:
        reason = ReplanReason.from_value(reason)
        return {
            ReplanReason.MISSING_REQUIRED_CONTEXT: "Required context is missing; add safe readonly context before continuing.",
            ReplanReason.MISSING_REQUIRED_PARAMETER: "A required user parameter is missing; ask for clarification.",
            ReplanReason.TOOL_ERROR_RECOVERABLE: "Tool failed in a potentially recoverable way; retry or use readonly fallback.",
            ReplanReason.TOOL_ERROR_BLOCKING: "Tool failed in a blocking way; report safely.",
            ReplanReason.TOOL_RESULT_EMPTY: "Tool returned an empty result; add fallback evidence or alternate readonly lookup.",
            ReplanReason.EVIDENCE_INSUFFICIENT: "Evidence is insufficient; retrieve additional readonly evidence.",
            ReplanReason.MEMORY_INSUFFICIENT: "Relevant memory was not found; continue without memory or ask for context.",
            ReplanReason.PERMISSION_BLOCKED: "Permission blocked the action; do not escalate permissions automatically.",
            ReplanReason.APPROVAL_REQUIRED: "User approval is required; wait for confirmation through WriteGateway.",
            ReplanReason.APPROVAL_DENIED: "Approval was denied or invalid; stop and report.",
            ReplanReason.TASK_DEPENDENCY_FAILED: "A dependent task failed; repair dependent readonly steps if allowed.",
            ReplanReason.MAX_REPLAN_LIMIT_REACHED: "Replan limit reached; stop looping and report safely.",
        }.get(reason, "Replan check required.")

    def _reason_for_event(self, event: ObservationEvent) -> ReplanReason:
        if event.observation_type == ObservationType.TOOL_ERROR:
            if event.severity == ObservationSeverity.BLOCKING:
                return ReplanReason.TOOL_ERROR_BLOCKING
            return ReplanReason.TOOL_ERROR_RECOVERABLE
        return REASON_BY_OBSERVATION.get(event.observation_type, ReplanReason.TOOL_ERROR_RECOVERABLE)

    @staticmethod
    def _suggested_patch(reason: ReplanReason, event: ObservationEvent) -> dict[str, Any]:
        if reason in {ReplanReason.TOOL_RESULT_EMPTY, ReplanReason.EVIDENCE_INSUFFICIENT}:
            return {"action": "add_readonly_fallback_task", "task_id": event.task_id}
        if reason == ReplanReason.MISSING_REQUIRED_CONTEXT:
            return {"action": "refresh_context_refs", "task_id": event.task_id}
        if reason == ReplanReason.APPROVAL_REQUIRED:
            return {"action": "wait_for_user_confirmation", "task_id": event.task_id, "auto_commit": False}
        return {"action": "report_or_retry_readonly", "task_id": event.task_id}
