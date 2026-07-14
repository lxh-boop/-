from __future__ import annotations

from agent.reflection import (
    CriticAction,
    CriticIssue,
    CriticIssueCategory,
    CriticPolicy,
    CriticResult,
    CriticSeverity,
)


def test_phase16_critic_policy_secret_blocks_and_redacts() -> None:
    policy = CriticPolicy()
    issue = CriticIssue(
        category=CriticIssueCategory.SENSITIVE_DATA_EXPOSURE,
        severity=CriticSeverity.BLOCKING,
        summary="confirmation_token leaked",
    )

    assert policy.classify_issue("confirmation_token=abc raw_tool_payload visible") is CriticIssueCategory.SENSITIVE_DATA_EXPOSURE
    assert policy.decide_action([issue]) is CriticAction.BLOCK_AND_REPORT
    assert policy.can_show_to_llm("confirmation_token", "abc") is False
    assert policy.can_show_to_ui("raw_tool_payload", {"x": 1}) is False
    assert policy.requires_redaction("db_path", "D:\\stock_daily_app\\data\\agent_quant.db") is True


def test_phase16_critic_policy_evidence_gap_requests_readonly_replan() -> None:
    policy = CriticPolicy()
    result = CriticResult(
        issues=[
            CriticIssue(
                category=CriticIssueCategory.EVIDENCE_INSUFFICIENT,
                severity=CriticSeverity.MEDIUM,
                summary="answer has insufficient source evidence",
            )
        ]
    )

    assert policy.decide_action(result) is CriticAction.REPLAN_READONLY
    assert policy.score_result(result) < 1.0


def test_phase16_critic_policy_write_boundary_requires_approval() -> None:
    policy = CriticPolicy()
    issue = CriticIssue(
        category=CriticIssueCategory.WRITE_WITHOUT_APPROVAL,
        severity=CriticSeverity.HIGH,
        summary="portfolio write proposal missing user approval",
    )

    assert policy.classify_issue("write commit without approval") is CriticIssueCategory.WRITE_WITHOUT_APPROVAL
    assert policy.decide_action([issue]) is CriticAction.REQUIRE_APPROVAL


def test_phase16_critic_policy_missing_user_info_asks_user() -> None:
    policy = CriticPolicy()
    issue = CriticIssue(
        category=CriticIssueCategory.MISSING_USER_INFO,
        severity=CriticSeverity.MEDIUM,
        summary="missing user risk preference",
    )

    assert policy.decide_action([issue]) is CriticAction.ASK_USER
