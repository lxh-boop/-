from __future__ import annotations

import json

from agent.reflection import (
    CriticAction,
    CriticEngine,
    CriticIssueCategory,
    CriticSeverity,
    ReflectionStore,
)


def test_phase16_critic_engine_safe_final_result_passes(tmp_path) -> None:
    engine = CriticEngine(output_dir=tmp_path)

    result = engine.criticize_final_result(
        answer_summary="Current portfolio summary is available.",
        success=True,
        tool_name="portfolio_state",
        run_id="run_ok",
        task_id="task_1",
        observation_refs=[{"observation_id": "obs_1"}],
    )

    assert result.action is CriticAction.PASS
    assert result.score == 1.0


def test_phase16_critic_engine_evidence_gap_requests_readonly_replan(tmp_path) -> None:
    engine = CriticEngine(output_dir=tmp_path)

    result = engine.criticize_final_result(
        answer_summary="相关新闻显示公司经营改善。",
        success=True,
        tool_name="stock_news",
        run_id="run_news",
        task_id="task_news",
        evidence_refs=[],
    )

    assert result.action is CriticAction.REPLAN_READONLY
    assert result.issues[0].category is CriticIssueCategory.EVIDENCE_INSUFFICIENT


def test_phase16_critic_engine_tool_failure_with_certain_answer_revises(tmp_path) -> None:
    engine = CriticEngine(output_dir=tmp_path)

    result = engine.criticize_tool_result_summary(
        result_summary={"success": False, "message": "tool failed"},
        answer_summary="The update must be completed successfully.",
        tool_name="scheduler_status",
        run_id="run_fail",
    )

    assert result.action is CriticAction.REVISE_ANSWER
    assert result.severity is CriticSeverity.HIGH


def test_phase16_critic_engine_write_without_approval_requires_approval(tmp_path) -> None:
    engine = CriticEngine(output_dir=tmp_path)

    result = engine.criticize_portfolio_proposal(
        proposal_summary={"operation": "adjust_position", "stock_code": "600519"},
        approval_refs=[],
        run_id="run_write",
    )

    assert result.action is CriticAction.REQUIRE_APPROVAL
    assert result.requires_user_confirmation is True


def test_phase16_reflection_store_sanitizes_secret_fields(tmp_path) -> None:
    engine = CriticEngine(output_dir=tmp_path)
    result = engine.criticize_final_result(
        answer_summary="api_key=abc D:\\stock_daily_app\\data\\agent_quant.db",
        success=True,
        tool_name="portfolio_state",
        run_id="run_secret",
        metadata={"confirmation_token": "abc123", "raw_tool_payload": [{"tool_call_id": "tool_1"}]},
    )

    engine.save_result(result, user_id="u1")
    text = (tmp_path / "reflection_logs" / "u1" / "run_secret.jsonl").read_text(encoding="utf-8")
    payload = json.loads(text)["critic_result"]

    assert "abc123" not in text
    assert "api_key" not in text
    assert "agent_quant.db" not in text
    assert "raw_tool_payload" not in text
    assert ReflectionStore(output_dir=tmp_path).list_results_by_run("run_secret", user_id="u1")
    assert payload["action"] == "BLOCK_AND_REPORT"
