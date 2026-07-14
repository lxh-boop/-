from pathlib import Path

from agent.communication import MessageStore, MessageType
from agent.context.context_builder import ContextManager
from agent.react import ObserveStore, ReplanDecisionStatus, record_executor_result_observation


def test_phase15_executor_success_generates_replan_skipped(tmp_path: Path):
    context_manager = ContextManager(output_dir=tmp_path)
    bundle = context_manager.create_initial_context(user_id="u1", query="q", conversation_id="conv_1", run_id="run_ok")

    result = record_executor_result_observation(
        {"success": True, "message": "done", "data": {"answer": "ok"}, "tool_name": "agent_executor"},
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv_1",
        run_id="run_ok",
        task_id="task_1",
        context_bundle=bundle,
    )

    assert result["replan_decision"]["status"] == ReplanDecisionStatus.SKIPPED.value
    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run_ok", user_id="u1")
    assert MessageType.OBSERVATION_CREATED in {message.message_type for message in messages}
    assert MessageType.REPLAN_SKIPPED in {message.message_type for message in messages}
    assert bundle.runtime_context.latest_replan_decision_id


def test_phase15_executor_failed_result_generates_replan_requested(tmp_path: Path):
    result = record_executor_result_observation(
        {"success": False, "message": "failed", "errors": ["missing context"], "tool_name": "agent_executor"},
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv_1",
        run_id="run_failed",
        task_id="task_1",
    )

    assert result["replan_decision"]["status"] == ReplanDecisionStatus.REQUESTED.value
    observations = ObserveStore(output_dir=tmp_path).list_observations_by_run("run_failed", user_id="u1")
    assert observations
    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run_failed", user_id="u1")
    assert MessageType.REPLAN_REQUESTED in {message.message_type for message in messages}


def test_phase15_executor_replan_message_does_not_expose_confirmation_token(tmp_path: Path):
    record_executor_result_observation(
        {
            "success": False,
            "message": "failed confirmation_token=abc123",
            "error_message": "bad token abc123",
            "data": {"confirmation_token": "abc123", "plan_id": "plan_1"},
            "tool_name": "agent_executor",
        },
        output_dir=tmp_path,
        user_id="u1",
        conversation_id="conv_1",
        run_id="run_secret",
        task_id="task_1",
    )

    log_text = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "message_logs" / "u1").glob("*.jsonl"))
    obs_text = (tmp_path / "react_logs" / "u1" / "run_secret.jsonl").read_text(encoding="utf-8")
    assert "abc123" not in log_text
    assert "abc123" not in obs_text
