from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_executor_does_not_use_keyword_task_synthesis():
    source = _read("agent/executor.py")
    function = source.split("def _normalise_readonly_multi_agent_tasks", 1)[1].split("def _merge_agent_task_results", 1)[0]
    assert "_query_has_any" not in function
    assert "wants_portfolio" not in function
    assert "wants_ranking" not in function
    assert "exact LLM plan" in function
    assert "executor.multi_intent.exact_dag" in source


def test_ui_has_no_legacy_agent_fallback():
    source = _read("app/pages/ai_agent.py")
    assert "answer_with_registry(" not in source
    assert '"fallback_used": False' in source


def test_old_stability_template_is_not_selected_by_aggregator():
    source = _read("agent/orchestration/result_aggregator.py")
    aggregate_body = source.split("def aggregate_multi_task_answer", 1)[1]
    assert "_aggregate_portfolio_stability_recommendation(" not in aggregate_body
    assert "_aggregate_target_portfolio(" in aggregate_body
    assert "_aggregate_portfolio_comparison(" in aggregate_body


def test_reflection_write_detection_is_structural_not_natural_language():
    source = _read("agent/reflection/critic_engine.py")
    function = source.split("def _looks_like_write_result", 1)[1].split("def _risk_conflict", 1)[0]
    assert "str(summary).lower()" not in function
    assert '"requires_confirmation"' in function
    assert '"operation_type"' in function
    assert '"plan_id"' in function


def test_console_trace_is_present_at_key_stages():
    expected = {
        "agent/intent_decomposition/layered_decomposer.py": ["RULE_HINTS"],
        "agent/intent_decomposition/llm_decomposer.py": ["LLM_USER_GOAL", "TASK_PLAN", "GOAL_REVIEW", "PLAN_REVIEW", "REPORT", "CRITIC"],
        "agent/goal_planning.py": ["SAFETY_VALIDATION", "COMPLETION_OBSERVE"],
        "agent/executor.py": ["REQUEST", "CONTEXT", "TASK_RESULT"],
        "agent/orchestration/multi_task_executor.py": ["TASK_PLAN_EXECUTION", "TASK_START", "TASK_RESULT"],
        "agent/tools/portfolio_comparison_tools.py": ["TARGET_DESIGN_INPUT", "TARGET_DESIGN", "TARGET_REPLAN", "TARGET_CONSTRUCTION"],
    }
    for relative, markers in expected.items():
        source = _read(relative)
        for marker in markers:
            assert marker in source


def test_more_stable_portfolio_is_designed_by_llm_not_requested_from_user():
    prompts = _read("agent/intent_decomposition/prompts.py")
    tools = _read("agent/tools/portfolio_comparison_tools.py")
    assert "portfolio.design_target_portfolio" in prompts
    assert "不要因为用户没有亲自指定" in prompts
    assert "让第二个 LLM 决策步骤" in prompts
    assert "请明确目标持仓数量、目标现金比例" not in prompts
    assert "LLM 已基于当前持仓、风险画像和排名设计目标组合参数" in tools
    assert "不会要求用户代替 Agent 设计参数" in tools


def test_v2_tool_permission_audit_accepts_canonical_llm_planned_tools():
    source = _read("agent/orchestration/multi_task_executor.py")
    function = source.split("def _tool_permission_errors", 1)[1].split("def _semantic_observer_trigger_reasons", 1)[0]
    assert "get_tool_registry_v2" in function
    assert "v2_definition.operation_type != OP_READ" in function
    assert "_validate_v2_call_arguments" in source


def test_completion_observe_is_printed_even_when_llm_observer_is_unavailable():
    source = _read("agent/goal_planning.py")
    function = source.split("def observe_goal_completion", 1)[1].split("def build_goal_planning_trace", 1)[0]
    assert function.count('"COMPLETION_OBSERVE"') >= 3
    assert '"llm_unavailable": True' in function


def test_construct_failure_replans_llm_instead_of_pushing_design_to_user():
    source = _read("agent/tools/portfolio_comparison_tools.py")
    assert '"next_action": "replan_target_design"' in source
    assert "需要由 LLM 根据实际比较结果重新设计" in source
