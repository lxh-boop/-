from agent.react import (
    ObservationEvent,
    ObservationSeverity,
    ObservationType,
    ReplanDecisionStatus,
    ReplanLimiter,
    ReplanPolicy,
    ReplanReason,
    ReplanScope,
)
from agent.communication.message_types import MessageType


def test_phase15_replan_policy_empty_result_requests_replan():
    policy = ReplanPolicy()
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TOOL_EMPTY_RESULT,
        severity=ObservationSeverity.MEDIUM,
        summary="empty result",
    )

    decision = policy.build_replan_decision(event, record=True)

    assert decision.status is ReplanDecisionStatus.REQUESTED
    assert decision.reason is ReplanReason.TOOL_RESULT_EMPTY
    assert decision.scope is ReplanScope.CURRENT_TASK
    assert decision.metadata["auto_commit"] is False


def test_phase15_replan_policy_tool_success_skips_replan():
    policy = ReplanPolicy()
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TOOL_SUCCESS,
        summary="ok",
    )

    decision = policy.build_replan_decision(event)

    assert decision.status is ReplanDecisionStatus.SKIPPED
    assert decision.scope is ReplanScope.NO_REPLAN


def test_phase15_replan_limiter_blocks_infinite_replan():
    limiter = ReplanLimiter(max_run_replans=2, max_task_replans=1, max_same_reason=1)
    policy = ReplanPolicy(limiter=limiter)
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_1",
        observation_type=ObservationType.TOOL_EMPTY_RESULT,
    )

    first = policy.build_replan_decision(event, record=True)
    second = policy.build_replan_decision(event, record=True)

    assert first.status is ReplanDecisionStatus.REQUESTED
    assert second.status is ReplanDecisionStatus.BLOCKED
    assert second.reason is ReplanReason.MAX_REPLAN_LIMIT_REACHED
    assert "same_reason_replan_limit_reached" in second.blocked_by


def test_phase15_replan_policy_approval_required_waits_for_write_gateway_not_commit():
    policy = ReplanPolicy()
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_approval",
        observation_type=ObservationType.APPROVAL_REQUIRED,
        approval_refs=[{"plan_id": "plan_1", "token_present": True}],
    )

    decision = policy.build_replan_decision(event, record=True)

    assert decision.status is ReplanDecisionStatus.WAIT_APPROVAL
    assert decision.reason is ReplanReason.APPROVAL_REQUIRED
    assert decision.scope is ReplanScope.PLAN_SUMMARY_ONLY
    assert "write_gateway_required" in decision.blocked_by
    assert decision.metadata["auto_commit"] is False
    assert decision.metadata["requires_write_gateway"] is True


def test_phase15_replan_policy_permission_block_does_not_escalate():
    policy = ReplanPolicy()
    event = ObservationEvent(
        run_id="run_1",
        task_id="task_permission",
        observation_type=ObservationType.TOOL_PERMISSION_BLOCKED,
    )

    decision = policy.build_replan_decision(event)

    assert decision.status is ReplanDecisionStatus.BLOCKED
    assert decision.reason is ReplanReason.PERMISSION_BLOCKED
    assert "permission_escalation_disallowed" in decision.blocked_by
    assert decision.metadata["permission_escalation_allowed"] is False


def test_phase15_message_type_replan_compatibility_exists():
    assert MessageType.OBSERVATION_CREATED.value == "OBSERVATION_CREATED"
    assert MessageType.REPLAN_REQUESTED.value == "REPLAN_REQUESTED"
    assert MessageType.REPLAN_SKIPPED.value == "REPLAN_SKIPPED"
    assert MessageType.REPLAN_APPLIED.value == "REPLAN_APPLIED"
    assert MessageType.REPLAN_BLOCKED.value == "REPLAN_BLOCKED"
