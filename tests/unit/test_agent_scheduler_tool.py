from __future__ import annotations

from agent.tool_engine import AGENT_MAIN, execute_tool


def test_agent_scheduler_tool_is_non_crashing(tmp_path) -> None:
    result = execute_tool(
        "system.scheduler_status",
        {},
        context={"output_dir": tmp_path},
        agent_type=AGENT_MAIN,
    )
    assert result.success is True
    assert result.data["status"] in {"success", "missing_status"}
    assert "latest_job_status" in result.data
