from pathlib import Path

from agent.communication import MessageStore, MessageType
from agent.context.context_builder import ContextManager
from agent.react import ObservationType, ObserveStore
from agent.tool_engine import (
    AGENT_READ,
    OP_READ,
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
    _result_schema,
    _schema,
)


def _description() -> str:
    return "\n".join(
        [
            "Function: test tool.",
            "Applies when: tests need a deterministic tool.",
            "Not for: writes.",
            "Preconditions: none.",
            "Main inputs: none.",
            "Main outputs: data.",
            "Side effects: none.",
        ]
    )


def _executor(handler):
    registry = ToolRegistry(
        [
            ToolDefinition(
                name="test.tool",
                display_name="Test Tool",
                description=_description(),
                input_schema=_schema({}),
                output_schema=_result_schema(),
                execution_handler=handler,
                operation_type=OP_READ,
                allowed_agent_types=[AGENT_READ],
                produced_outputs=["items"],
            )
        ]
    )
    return ToolExecutor(registry=registry)


def test_phase15_tool_executor_success_generates_observation_and_message(tmp_path: Path):
    context_manager = ContextManager(output_dir=tmp_path)
    bundle = context_manager.create_initial_context(user_id="u1", query="q", conversation_id="conv_1", run_id="run_1")
    executor = _executor(lambda _args, _context: {"success": True, "message": "ok", "data": {"items": [1]}})

    result = executor.execute(
        "test.tool",
        {},
        context={"user_id": "u1", "output_dir": tmp_path, "run_id": "run_1", "conversation_id": "conv_1"},
        context_bundle=bundle,
        agent_type=AGENT_READ,
    )

    assert result.success is True
    observations = ObserveStore(output_dir=tmp_path).list_observations_by_run("run_1", user_id="u1")
    assert observations[0].observation_type is ObservationType.TOOL_SUCCESS
    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run_1", user_id="u1")
    assert MessageType.OBSERVATION_CREATED in {message.message_type for message in messages}
    assert MessageType.REPLAN_SKIPPED in {message.message_type for message in messages}
    assert bundle.runtime_context.observation_refs


def test_phase15_tool_executor_empty_result_generates_empty_observation(tmp_path: Path):
    executor = _executor(lambda _args, _context: {"success": True, "message": "empty", "data": {"items": []}})

    result = executor.execute(
        "test.tool",
        {},
        context={"user_id": "u1", "output_dir": tmp_path, "run_id": "run_empty", "conversation_id": "conv_1"},
        agent_type=AGENT_READ,
    )

    assert result.success is True
    observations = ObserveStore(output_dir=tmp_path).list_observations_by_run("run_empty", user_id="u1")
    assert observations[0].observation_type is ObservationType.TOOL_EMPTY_RESULT
    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run_empty", user_id="u1")
    assert MessageType.REPLAN_REQUESTED in {message.message_type for message in messages}


def test_phase15_tool_executor_exception_generates_tool_error_observation(tmp_path: Path):
    def boom(_args, _context):
        raise RuntimeError("boom confirmation_token=abc123")

    executor = _executor(boom)
    result = executor.execute(
        "test.tool",
        {},
        context={"user_id": "u1", "output_dir": tmp_path, "run_id": "run_error", "conversation_id": "conv_1"},
        agent_type=AGENT_READ,
    )

    assert result.success is False
    observations = ObserveStore(output_dir=tmp_path).list_observations_by_run("run_error", user_id="u1")
    assert observations[0].observation_type is ObservationType.TOOL_ERROR
    text = (tmp_path / "react_logs" / "u1" / "run_error.jsonl").read_text(encoding="utf-8")
    assert "abc123" not in text
    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run_error", user_id="u1")
    assert MessageType.OBSERVATION_CREATED in {message.message_type for message in messages}
