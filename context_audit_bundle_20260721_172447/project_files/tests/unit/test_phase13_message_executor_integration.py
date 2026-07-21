from __future__ import annotations

import json

from agent.communication import MessageStore, MessageType
from agent.executor import run_agent_request
from agent_control_center_utils import write_agent_fixture


def test_executor_publishes_core_phase13_messages(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)

    result = run_agent_request(
        "查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
    )

    messages = MessageStore(output_dir=output_dir).list_messages_by_run(result["run_id"], user_id="u1")
    types = {message.message_type for message in messages}
    encoded = json.dumps([message.to_dict() for message in messages], ensure_ascii=False, sort_keys=True)

    assert result["success"] is True
    assert MessageType.USER_REQUEST in types
    assert MessageType.CONTEXT_CREATED in types
    assert MessageType.GOAL_PARSED in types
    assert MessageType.TASK_PLANNED in types
    assert MessageType.FINAL_REPORT in types
    assert "confirmation_token" not in encoded
    assert "agent_quant.db" not in encoded

