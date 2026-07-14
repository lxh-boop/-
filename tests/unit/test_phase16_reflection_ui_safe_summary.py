from __future__ import annotations

import json

from app.reflection_ui import (
    build_reflection_health_summary,
    build_reflection_safe_summary,
    format_reflection_caption,
)
from app.pages.ai_agent import PHASE15_VISIBLE_MESSAGE_WINDOW
from agent.reflection import CriticAction, CriticIssue, CriticIssueCategory, CriticResult, CriticSeverity, ReflectionStore


def test_phase16_reflection_safe_summary_hides_secrets_and_raw_payloads() -> None:
    result = {
        "run_id": "run_secret",
        "reflection": CriticResult(
            action=CriticAction.BLOCK_AND_REPORT,
            severity=CriticSeverity.BLOCKING,
            target_summary="api_key=abc D:\\stock_daily_app\\data\\agent_quant.db",
            metadata={"confirmation_token": "abc123", "raw_tool_payload": [{"tool_call_id": "tool_1"}]},
        ).to_dict(),
    }

    summary = build_reflection_safe_summary(result)
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)

    assert summary["reflection_available"] is True
    assert "confirmation_token" not in encoded
    assert "abc123" not in encoded
    assert "api_key" not in encoded
    assert "agent_quant.db" not in encoded
    assert "raw_tool_payload" not in encoded


def test_phase16_reflection_safe_summary_empty_is_safe() -> None:
    summary = build_reflection_safe_summary({})

    assert summary["reflection_available"] is False
    assert summary["issues"] == []
    assert summary["safety"]["secrets_redacted"] is True
    assert format_reflection_caption(summary) == ""


def test_phase16_reflection_safe_summary_keeps_blocking_issue_summary_only() -> None:
    result = {
        "run_id": "run_block",
        "reflection": CriticResult(
            action=CriticAction.BLOCK_AND_REPORT,
            severity=CriticSeverity.BLOCKING,
            issues=[
                CriticIssue(
                    category=CriticIssueCategory.SENSITIVE_DATA_EXPOSURE,
                    severity=CriticSeverity.BLOCKING,
                    summary="Unsafe draft contained sensitive runtime fields.",
                    detail={"raw_tool_payload": {"secret": "leak_marker_123"}},
                )
            ],
        ).to_dict(),
    }

    summary = build_reflection_safe_summary(result)
    encoded = json.dumps(summary, ensure_ascii=False, sort_keys=True)

    assert summary["issue_count"] == 1
    assert summary["issues"][0]["issue_type"] == "SENSITIVE_DATA_EXPOSURE"
    assert "raw_tool_payload" not in encoded
    assert "leak_marker_123" not in encoded


def test_phase16_reflection_health_summary_uses_safe_relative_summary(tmp_path) -> None:
    result = CriticResult(run_id="run_1", action=CriticAction.PASS, target_summary="ok")
    ReflectionStore(output_dir=tmp_path).save_result(result, user_id="u1")

    health = build_reflection_health_summary(user_id="u1", output_dir=tmp_path)
    encoded = json.dumps(health, ensure_ascii=False, sort_keys=True)

    assert health["status"] == "ok"
    assert health["latest_critic_count"] == 1
    assert health["critic_pass_count"] == 1
    assert "reflection_logs/u1/files=1" in encoded
    assert str(tmp_path) not in encoded


def test_phase16_reflection_ui_does_not_change_phase15_default_window() -> None:
    assert PHASE15_VISIBLE_MESSAGE_WINDOW == 10
