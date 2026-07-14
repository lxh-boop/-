from __future__ import annotations

import json

from agent.reflection import (
    CriticAction,
    CriticIssue,
    CriticIssueCategory,
    CriticResult,
    CriticSanitizer,
    CriticSeverity,
    CriticTargetType,
    CriticWindow,
)


def test_phase16_critic_result_serializes_roundtrip() -> None:
    result = CriticResult(
        run_id="run_1",
        task_id="task_1",
        target_type=CriticTargetType.FINAL_REPORT,
        target_summary="portfolio report",
        action=CriticAction.REVISE_ANSWER,
        severity=CriticSeverity.MEDIUM,
        score=0.72,
        issues=[
            CriticIssue(
                category=CriticIssueCategory.EVIDENCE_INSUFFICIENT,
                severity=CriticSeverity.MEDIUM,
                summary="needs more evidence",
                evidence_refs=[{"chunk_id": "chunk_1"}],
            )
        ],
        observation_refs=[{"observation_id": "obs_1"}],
    )

    data = result.to_dict()

    assert data["critic_id"].startswith("critic_")
    assert data["target_type"] == "FINAL_REPORT"
    assert data["issues"][0]["category"] == "EVIDENCE_INSUFFICIENT"

    restored = CriticResult.from_dict(data)
    assert restored.action is CriticAction.REVISE_ANSWER
    assert restored.severity is CriticSeverity.MEDIUM
    assert restored.issues[0].category is CriticIssueCategory.EVIDENCE_INSUFFICIENT


def test_phase16_critic_action_contract_complete() -> None:
    required = {
        "PASS",
        "REVISE_ANSWER",
        "REPLAN_READONLY",
        "ASK_USER",
        "REQUIRE_APPROVAL",
        "BLOCK_AND_REPORT",
        "HANDOFF_REQUESTED",
    }
    assert required <= {item.value for item in CriticAction}


def test_phase16_critic_sanitizer_hides_secrets_paths_and_raw_payloads() -> None:
    result = CriticResult(
        target_summary="api_key=abc D:\\stock_daily_app\\data\\agent_quant.db",
        metadata={
            "confirmation_token": "secret-token",
            "raw_tool_payload": [{"tool_call_id": "tool_1", "private": "hidden"}],
            "raw_positions": [{"stock_code": "600519", "quantity": 100}],
            "stack_trace": "Traceback (most recent call last): File \"D:\\x.py\", line 1",
        },
    )

    safe = CriticSanitizer().sanitize_for_llm(result)
    encoded = json.dumps(safe, ensure_ascii=False)

    assert "confirmation_token" not in encoded
    assert "secret-token" not in encoded
    assert "api_key" not in encoded
    assert "agent_quant.db" not in encoded
    assert "Traceback" not in encoded
    assert "raw_tool_payload" not in encoded
    assert "raw_positions" not in encoded
    assert "tool_payload_summary" in encoded
    assert "positions_summary" in encoded


def test_phase16_critic_window_keeps_blocking_issues() -> None:
    normal = CriticResult(
        action=CriticAction.PASS,
        target_summary="ok " + ("x" * 500),
    )
    blocking = CriticResult(
        action=CriticAction.BLOCK_AND_REPORT,
        severity=CriticSeverity.BLOCKING,
        target_summary="must keep",
        issues=[
            CriticIssue(
                category=CriticIssueCategory.SENSITIVE_DATA_EXPOSURE,
                severity=CriticSeverity.BLOCKING,
                summary="secret leaked",
            )
        ],
    )

    window = CriticWindow(default_budget=180)
    trimmed = window.trim_critic_results_to_budget([normal, blocking], budget=180)
    blocking_only = window.keep_blocking_issues([normal, blocking])

    assert any(item.get("target_summary") == "must keep" for item in trimmed)
    assert len(blocking_only) == 1
    assert blocking_only[0]["action"] == "BLOCK_AND_REPORT"
