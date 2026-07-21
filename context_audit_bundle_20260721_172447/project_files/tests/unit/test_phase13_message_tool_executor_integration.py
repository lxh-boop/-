from __future__ import annotations

import json

from agent.communication import MessageStore, MessageType
from agent.context import ContextBundle
from agent.tool_engine import AGENT_READ, OP_READ, ToolDefinition, ToolExecutor, ToolRegistry


def _definition(name: str = "test.phase13_echo", *, fail: bool = False) -> ToolDefinition:
    def handler(arguments, context):
        if fail:
            raise RuntimeError("handler boom")
        return {
            "success": True,
            "message": "ok",
            "data": {"echo": arguments.get("value"), "context_id": context.get("context_bundle_id")},
            "tool_name": name,
        }

    return ToolDefinition(
        name=name,
        display_name="Phase13 Echo",
        description="\n".join(
            [
                "Function: phase13 echo tool.",
                "Applies when: testing message integration.",
                "Not for: production trading.",
                "Preconditions: none.",
                "Main inputs: value.",
                "Main outputs: echo.",
                "Side effects: None; read-only.",
            ]
        ),
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": []},
        output_schema={"type": "object", "required_data_keys": ["echo"]},
        execution_handler=handler,
        operation_type=OP_READ,
        allowed_agent_types=[AGENT_READ],
        permission_scope=OP_READ,
    )


def test_tool_executor_publishes_call_result_and_artifact_messages(tmp_path) -> None:
    bundle = ContextBundle(user_id="u1", conversation_id="conv1", run_id="run1", task_id="task1")
    executor = ToolExecutor(registry=ToolRegistry([_definition()]))

    result = executor.execute(
        "test.phase13_echo",
        {"value": "hello", "confirmation_token": "must-not-log"},
        context={"user_id": "u1", "output_dir": tmp_path, "run_id": "run1", "conversation_id": "conv1", "task_id": "task1"},
        context_bundle=bundle,
        agent_type=AGENT_READ,
    )

    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run1", user_id="u1")
    types = {message.message_type for message in messages}
    encoded = json.dumps([message.to_dict() for message in messages], ensure_ascii=False, sort_keys=True)

    assert result.success is True
    assert MessageType.TOOL_CALL_REQUESTED in types
    assert MessageType.TOOL_RESULT_RECEIVED in types
    assert MessageType.ARTIFACT_CREATED in types
    assert "must-not-log" not in encoded
    assert "argument_keys" in encoded


def test_tool_executor_failure_publishes_error_message(tmp_path) -> None:
    executor = ToolExecutor(registry=ToolRegistry([_definition("test.phase13_fail", fail=True)]))

    result = executor.execute(
        "test.phase13_fail",
        {},
        context={"user_id": "u1", "output_dir": tmp_path, "run_id": "run1", "conversation_id": "conv1"},
        agent_type=AGENT_READ,
    )

    messages = MessageStore(output_dir=tmp_path).list_messages_by_run("run1", user_id="u1")

    assert result.success is False
    assert any(message.message_type == MessageType.ERROR_RAISED for message in messages)

