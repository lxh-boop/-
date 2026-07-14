from __future__ import annotations

import json

from agent.communication import MessageStore, MessageType
from agent.tool_engine import AGENT_MAIN, execute_tool
from agent.write_gateway import execute_confirmed_plan_v2
from agent_control_center_utils import write_agent_fixture


def test_write_gateway_and_confirmation_publish_approval_messages_without_token(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, cash=100000.0)
    preview = execute_tool(
        "capital.change.preview",
        {"user_id": "u1", "flow_type": "deposit", "amount": 1000.0, "effective_date": "2026-06-12"},
        context={"user_id": "u1", "output_dir": output_dir, "db_path": db_path, "run_id": "run1", "conversation_id": "conv1"},
        agent_type=AGENT_MAIN,
    )

    assert preview.success is True
    committed = execute_confirmed_plan_v2(
        preview.data["plan_id"],
        preview.data["confirmation_token"],
        "u1",
        conversation_id="conv1",
        run_id="run1",
        output_dir=output_dir,
        db_path=db_path,
    )

    messages = MessageStore(output_dir=output_dir).list_messages_by_run("run1", user_id="u1")
    types = {message.message_type for message in messages}
    encoded = json.dumps([message.to_dict() for message in messages], ensure_ascii=False, sort_keys=True)

    assert committed.success is True
    assert MessageType.APPROVAL_REQUESTED in types
    assert MessageType.APPROVAL_RESULT_RECEIVED in types
    assert preview.data["confirmation_token"] not in encoded
    assert "confirmation_token" not in encoded
