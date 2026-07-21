from __future__ import annotations

import pytest

from agent.communication.message_types import MessageType
from agent.logic_integrity import (
    LogicIntegrityResult,
    terminal_completion_payload,
    terminal_critic_payload,
)
from agent.replan_execution import consume_readonly_replan
from agent.runtime_reliability import RuntimeBudget, RuntimeBudgetExceeded, RuntimePolicy
from agent.top_k import resolve_business_top_k
from agent.tools.portfolio_comparison_tools import _allocation_validation_feedback


def test_llm_budget_limits_are_disabled_without_disabling_tool_limit():
    policy = RuntimePolicy(max_tool_calls=1, hard_llm_call_budget=1, hard_token_budget=1)
    budget = RuntimeBudget(policy)
    for _ in range(3):
        budget.record_llm_call(token_estimate=100)
        budget.ensure_can_start_llm(additional_tokens=100)
    assert budget.llm_budget_exhausted is False

    budget.record_tool_call()
    with pytest.raises(RuntimeBudgetExceeded, match="max_tool_calls"):
        budget.ensure_can_start_tool()


def test_llm_budget_limits_can_be_explicitly_enabled_for_diagnostics():
    policy = RuntimePolicy(
        enable_llm_budget_limits=True,
        hard_llm_call_budget=1,
        hard_token_budget=9999,
    )
    budget = RuntimeBudget(policy)
    budget.record_llm_call()
    with pytest.raises(RuntimeBudgetExceeded, match="hard_llm_call_budget"):
        budget.ensure_can_start_llm()


def test_replan_state_counts_only_an_executed_round_and_records_audit_fields():
    existing = {
        "state": {"success": True, "intent": "portfolio_state", "data": {"positions": []}},
        "ranking": {"success": True, "intent": "ranking", "data": {"records": [{"stock_code": "000001.SZ"}]}},
    }

    result = consume_readonly_replan(
        source="completion",
        action="replan_readonly",
        replan_count=0,
        replan_limit=2,
        replan_audit=[],
        task_results=existing,
        missing_outputs=["target_portfolio"],
        execute_plan=lambda tasks: {
            "execution_status": "completed",
            "task_results": {
                task["task_id"]: {"success": True, "intent": task["intent"], "data": {"target_portfolio": {"ok": True}}}
                for task in tasks
            },
        },
    )

    state = result["replan_state"]
    assert result["replan_count"] == 1
    assert state["executed_rounds"] == 1
    assert state["attempted_rounds"] == 1
    audit = result["replan_audit"][-1]
    for key in (
        "round", "trigger_sources", "missing_outputs_before", "missing_outputs_after",
        "request_signature", "plan_signature", "result_signature", "planned_tasks",
        "executed_tasks", "new_or_changed_outputs", "progress_status", "requested_at", "finished_at",
    ):
        assert key in audit
    assert audit["executed"] is True


def test_terminal_completion_and_critic_are_deterministic_and_do_not_request_replan():
    integrity = LogicIntegrityResult(
        status="logic_error",
        errors=["target_design_constraint_unreliable"],
        safe_to_continue=False,
        safe_to_answer=False,
        safe_to_write=False,
        recommended_action="feature_unavailable",
        error_code="target_design_constraint_unreliable",
    )
    completion = terminal_completion_payload(integrity)
    critic = terminal_critic_payload(integrity)
    assert completion["next_action"] == "report_limitation"
    assert critic["action"] == "BLOCK_AND_REPORT"
    assert critic["suppressed_action"] == "REPLAN_READONLY"


def test_target_constraints_reject_single_position_and_unverifiable_industry():
    universe = {
        "000001.SZ": {"stock_code": "000001.SZ", "stock_name": "A", "industry": ""},
        "000002.SZ": {"stock_code": "000002.SZ", "stock_name": "B", "industry": ""},
    }
    _, feedback = _allocation_validation_feedback(
        raw_candidates=[
            {"stock_code": "000001.SZ", "target_weight": 0.70},
            {"stock_code": "000002.SZ", "target_weight": 0.20},
        ],
        requested_cash_weight=0.10,
        universe_map=universe,
        max_single_weight=0.08,
        max_industry_weight=0.30,
        constraint_sources={"max_single_weight": "user_profile", "max_industry_weight": "user_profile"},
        design_rationale=["组合符合 8% 单票限制"],
    )
    codes = {item["code"] for item in feedback["errors"]}
    assert {"single_position_limit_exceeded", "industry_constraint_unverifiable", "design_explanation_conflict"} <= codes
    assert feedback["repairable"] is False


def test_business_top_k_uses_target_count_times_redundancy_before_defaults():
    assert resolve_business_top_k(target_position_count=6) == 12
    assert resolve_business_top_k(target_position_count=6, task_top_k=7) == 7
    assert resolve_business_top_k(target_position_count=6, user_explicit_top_k=9, task_top_k=7) == 9
    assert resolve_business_top_k(request_default_top_k=13) == 13


def test_final_response_has_a_dedicated_message_type():
    assert MessageType.FINAL_RESPONSE.value == "FINAL_RESPONSE"
