from agent.communication import MessageStore
from agent.handoff import (
    AgentRole,
    HandoffCoordinator,
    HandoffRequest,
    HandoffResult,
    HandoffStatus,
)


def test_phase17_handoff_coordinator_publishes_request_accept_result(tmp_path) -> None:
    coordinator = HandoffCoordinator(
        user_id="u1",
        output_dir=tmp_path,
        conversation_id="conv1",
        run_id="run1",
    )
    request = coordinator.plan_handoff(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="need evidence",
        task_id="task1",
        input_summary={"query": "news"},
        tool_names=["stock_rag"],
    )

    result = coordinator.execute_handoff(
        request,
        lambda req: HandoffResult(
            handoff_id=req.handoff_id,
            conversation_id=req.conversation_id,
            run_id=req.run_id,
            task_id=req.task_id,
            target_role=req.target_role,
            status=HandoffStatus.SUCCEEDED,
            summary="evidence ready",
        ),
    )

    assert result.status == HandoffStatus.SUCCEEDED
    merged = coordinator.merge_handoff_results()
    assert merged["handoff_count"] == 1
    assert merged["roles_used"] == ["EVIDENCE_RETRIEVER"]
    assert merged["blocked_handoff_count"] == 0

    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run1", user_id="u1")
    message_types = [message.message_type.value for message in messages]
    assert "HANDOFF_REQUESTED" in message_types
    assert "HANDOFF_ACCEPTED" in message_types
    assert "HANDOFF_RESULT" in message_types


def test_phase17_handoff_coordinator_blocks_specialist_write_tool(tmp_path) -> None:
    coordinator = HandoffCoordinator(user_id="u1", output_dir=tmp_path, conversation_id="conv1", run_id="run1")
    request = HandoffRequest(
        conversation_id="conv1",
        run_id="run1",
        task_id="task_bad",
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="bad write escalation",
        allowed_tools=["approval.confirm_plan"],
    )

    called = {"value": False}

    def _runner(_: HandoffRequest) -> HandoffResult:
        called["value"] = True
        return HandoffResult(status=HandoffStatus.SUCCEEDED)

    result = coordinator.execute_handoff(request, _runner)
    assert result.status == HandoffStatus.BLOCKED
    assert called["value"] is False
    assert coordinator.stop_on_blocking_result()

    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run1", user_id="u1")
    assert any(message.message_type.value == "HANDOFF_BLOCKED" for message in messages)


def test_phase17_handoff_depth_and_role_repeat_limits(tmp_path) -> None:
    coordinator = HandoffCoordinator(
        user_id="u1",
        output_dir=tmp_path,
        conversation_id="conv1",
        run_id="run1",
        max_handoff_depth=2,
        same_role_repeat=1,
    )
    assert coordinator.limit_handoff_depth(0) is True
    assert coordinator.limit_handoff_depth(2) is False

    request = coordinator.plan_handoff(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="first",
        tool_names=["stock_news"],
    )
    coordinator.execute_handoff(
        request,
        lambda req: HandoffResult(handoff_id=req.handoff_id, target_role=req.target_role, status=HandoffStatus.SUCCEEDED),
    )
    second = coordinator.plan_handoff(
        source_role=AgentRole.COORDINATOR,
        target_role=AgentRole.EVIDENCE_RETRIEVER,
        reason="repeat",
        tool_names=["stock_rag"],
    )
    repeated = coordinator.execute_handoff(
        second,
        lambda req: HandoffResult(handoff_id=req.handoff_id, target_role=req.target_role, status=HandoffStatus.SUCCEEDED),
    )
    assert repeated.status == HandoffStatus.BLOCKED
    assert "same_role_repeat" in repeated.summary
