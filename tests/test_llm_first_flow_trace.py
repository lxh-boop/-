from __future__ import annotations

import os

from agent.console_trace import flow_event


def test_flow_event_prints_stage_and_safe_intermediate_payload(capsys, monkeypatch):
    monkeypatch.setenv("AGENT_FLOW_TRACE", "1")
    monkeypatch.setenv("AGENT_FLOW_TRACE_MAX_CHARS", "30000")

    flow_event(
        "LLM_USER_GOAL",
        {
            "rule_hints": {
                "action": "recommend",
                "object": "portfolio",
                "authoritative": False,
            },
            "user_goal": {
                "action": "construct",
                "expected_outputs": ["target_portfolio", "current_vs_target"],
                "reason_summary": "用户要求更稳健的完整目标组合，但未要求执行。",
            },
            "api_key": "secret-key",
            "confirmation_token": "secret-token",
            "db_path": r"D:\\stock_daily_app\\database\\agent.db",
            "raw_payload": {"hidden": True},
        },
        run_id="run-1",
        task_id="task-plan",
    )

    output = capsys.readouterr().out
    assert "[AGENT-FLOW][LLM_USER_GOAL]" in output
    assert '"action": "construct"' in output
    assert '"target_portfolio"' in output
    assert '"authoritative": false' in output
    assert "secret-key" not in output
    assert "secret-token" not in output
    assert "D:\\stock_daily_app" not in output
    assert '"api_key": "[REDACTED]"' in output
    assert '"confirmation_token": "[REDACTED]"' in output
    assert '"db_path": "[REDACTED_PATH]"' in output
    assert '"raw_payload": "[REDACTED_RAW]"' in output


def test_flow_trace_can_be_disabled(capsys, monkeypatch):
    monkeypatch.setenv("AGENT_FLOW_TRACE", "0")
    flow_event("TASK_PLAN", {"tasks": ["task_1"]})
    assert capsys.readouterr().out == ""
