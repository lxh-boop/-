from __future__ import annotations

from agent.executor import run_agent_request
from agent.runtime import load_run_snapshot
from agent_control_center_utils import write_agent_fixture


def test_run_agent_request_persists_unified_runtime_trace(tmp_path) -> None:
    output_dir, db_path = write_agent_fixture(tmp_path, with_position=True, cash=100000.0)

    result = run_agent_request(
        "\u67e5\u770b\u5f53\u524d\u6a21\u62df\u76d8\u6301\u4ed3",
        user_id="u1",
        output_dir=output_dir,
        db_path=db_path,
        reply_language="zh",
    )

    assert result["success"] is True
    assert result["run_id"]
    assert result["runtime"]["status"] in {"completed", "partially_completed"}

    snapshot = load_run_snapshot(db_path, result["run_id"])
    assert snapshot["run"]["run_id"] == result["run_id"]
    assert snapshot["run"]["status"] == result["runtime"]["status"]
    assert snapshot["steps"]
    assert snapshot["tool_calls"]
    assert any(call["tool_name"] in {"portfolio_state", "multi_intent_executor"} for call in snapshot["tool_calls"])
    assert snapshot["sources"]
