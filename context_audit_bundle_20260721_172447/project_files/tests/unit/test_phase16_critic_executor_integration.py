from __future__ import annotations

import json

from agent.communication import MessageStore, MessageType
from agent.executor import run_agent_request
from agent_control_center_utils import write_agent_fixture


def test_phase16_executor_records_reflection_result_message(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, user_id="u1", with_position=True)

    result = run_agent_request(
        "查看当前模拟盘持仓",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
    )

    messages = MessageStore(output_dir=output_dir).list_messages_by_run(result["run_id"], user_id="u1")
    message_types = {message.message_type for message in messages}
    encoded_result = json.dumps(result, ensure_ascii=False, sort_keys=True)
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in (output_dir / "message_logs" / "u1").glob("*.jsonl"))
    reflection_text = "\n".join(path.read_text(encoding="utf-8") for path in (output_dir / "reflection_logs" / "u1").glob("*.jsonl"))

    assert result["success"] is True
    assert result["reflection"]["critic_id"].startswith("critic_")
    assert result["reflection"]["action"] == "PASS"
    assert MessageType.REFLECTION_REQUESTED in message_types
    assert MessageType.REFLECTION_RESULT in message_types
    assert "confirmation_token" not in encoded_result
    assert "agent_quant.db" not in encoded_result
    assert "raw_tool_payload" not in encoded_result
    assert "confirmation_token" not in log_text
    assert "agent_quant.db" not in log_text
    assert "raw_tool_payload" not in log_text
    assert "confirmation_token" not in reflection_text
    assert "agent_quant.db" not in reflection_text
    assert "raw_tool_payload" not in reflection_text
