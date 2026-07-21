from agent.collaboration_v2.control_gateway import ControlGateway
from agent.collaboration_v2.entry_decision import EntryDecision, RequestMode


def test_confirmation_without_plan_id_returns_need_context_without_legacy_route(tmp_path):
    gateway = ControlGateway(output_dir=tmp_path / "outputs", db_path=None)
    result = gateway.execute(
        decision=EntryDecision(mode=RequestMode.CONFIRM),
        query="确认执行",
        user_id="u1",
        session_id="s1",
        run_id="r1",
        language="zh",
        execution_context={},
    )
    assert result["need_clarification"] is True
    assert result["control_action"] == "confirm"
    assert result["effective_intent"] == "confirm_execute"
    assert result["tool_calls"] == []
