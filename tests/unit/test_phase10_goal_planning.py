from __future__ import annotations

from agent.goal_planning import (
    TaskPlan,
    UserGoal,
    _technical_fallback_observe,
    business_rule_candidates,
    build_goal_planning_trace,
    observe_goal_completion,
    plan_from_user_goal,
    validate_task_plan,
)
from agent.intent_decomposition.schemas import IntentDecomposition, IntentTask
from agent.router import route_agent_query


def _decomposition(tasks: list[IntentTask]) -> IntentDecomposition:
    return IntentDecomposition(
        query="推荐一个比现在更稳健的持仓，并说明为什么稳健",
        route_layer="rule_fallback",
        tasks=tasks,
        is_multi_intent=len(tasks) > 1,
        confidence=0.7,
    )


def test_business_portfolio_keyword_is_object_candidate_not_tool() -> None:
    candidates = business_rule_candidates("当前持仓风险怎么样")

    assert any(candidate.intent == "portfolio_object" for candidate in candidates)
    assert all(candidate.intent != "portfolio_state" for candidate in candidates)


def test_pure_portfolio_state_query_uses_validated_fast_path() -> None:
    routed = route_agent_query("查看当前持仓", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert routed.intent == "portfolio_state"
    assert trace["semantic_goal"]["action"] == "query_portfolio_state"
    assert trace["fast_path_selected"] is True
    assert trace["plan_validation"]["valid"] is True


def test_recommendation_cannot_return_only_portfolio_state() -> None:
    routed = route_agent_query("推荐一个比现在更稳健的持仓，并说明为什么稳健", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]
    intents = [task["intent"] for task in routed.decomposition["tasks"]]

    assert routed.intent == "multi_intent"
    assert trace["semantic_goal"]["action"] == "recommend_portfolio"
    assert trace["fast_path_selected"] is False
    assert {"portfolio_state", "portfolio_risk", "ranking"} <= set(intents)


def test_today_adjustment_is_recommendation_not_immediate_write() -> None:
    routed = route_agent_query("直接说今天的持仓应该修改成什么样", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]
    intents = [task["intent"] for task in routed.decomposition["tasks"]]

    assert routed.intent == "multi_intent"
    assert trace["semantic_goal"]["action"] == "recommend_portfolio_adjustment"
    assert trace["semantic_goal"]["requires_write"] is False
    assert "confirm_execute" not in intents


def test_portfolio_risk_request_plans_state_and_risk() -> None:
    routed = route_agent_query("分析当前持仓风险", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]
    intents = [task["intent"] for task in routed.decomposition["tasks"]]

    assert routed.intent == "multi_intent"
    assert trace["semantic_goal"]["action"] == "analyze_portfolio_risk"
    assert intents == ["portfolio_state", "portfolio_risk"]


def test_follow_up_explanation_inherits_previous_goal() -> None:
    previous_goal = {
        "action": "recommend_portfolio",
        "objects": ["current_portfolio"],
        "expected_outputs": ["target_portfolio", "reasons"],
    }
    routed = route_agent_query(
        "为什么这样调整",
        enable_llm=False,
        context={"previous_user_goal": previous_goal, "previous_result_summary": "stable recommendation"},
    )
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["is_follow_up"] is True
    assert trace["semantic_goal"]["action"] == "explain_previous_plan"
    assert routed.intent == "multi_intent"


def test_fallback_always_produces_user_goal() -> None:
    routed = route_agent_query("你好", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["semantic_goal"]["action"] in {"fallback_intent", "query_portfolio_state"}
    assert trace["task_plan"]["tasks"]
    assert "shadow_mode" in trace


def test_validator_blocks_incomplete_recommendation_plan() -> None:
    old = _decomposition([IntentTask(task_id="task_1", intent="portfolio_state")])
    trace = build_goal_planning_trace("推荐一个比现在更稳健的持仓，并说明为什么稳健", old)
    goal = trace["semantic_goal"]
    incomplete_plan = TaskPlan(
        tasks=[IntentTask(task_id="task_1", intent="portfolio_state")],
        dependencies={"task_1": []},
        expected_outputs=goal["expected_outputs"],
        completion_contract={"must_produce": goal["expected_outputs"]},
    )

    validation = validate_task_plan(UserGoal(**goal), incomplete_plan)

    assert validation.valid is False
    assert "recommendation_missing_portfolio_risk" in validation.errors
    assert "recommendation_missing_market_evidence" in validation.errors


def test_observe_marks_tool_success_but_goal_incomplete_as_partial() -> None:
    old = _decomposition([IntentTask(task_id="task_1", intent="portfolio_state")])
    trace = build_goal_planning_trace("推荐一个比现在更稳健的持仓，并说明为什么稳健", old)

    observed = observe_goal_completion(
        trace["semantic_goal"],
        {"task_results": {"task_1": {"intent": "portfolio_state", "success": True}}},
    )

    assert observed.status == "partial"
    assert "target_portfolio" in observed.missing_outputs


def test_fallback_observe_completes_when_artifact_satisfies_output_contract() -> None:
    observed = _technical_fallback_observe(
        {"expected_outputs": ["market_evidence"]},
        {
            "result": {
                "success": True,
                "metadata": {
                    "artifact_ref": {
                        "produced_outputs": ["evidence", "market_evidence"],
                    }
                },
            }
        },
    )

    assert observed.status == "complete"
    assert observed.next_action == "finish"
    assert observed.missing_outputs == []
    assert "market_evidence" in observed.produced_outputs


def test_fallback_observe_uses_registered_tool_output_contract() -> None:
    observed = _technical_fallback_observe(
        {"expected_outputs": ["market_evidence"]},
        {
            "result": {
                "success": True,
                "tool_name": "stock_rag",
                "data": {"chunks": [{"chunk_id": "chunk_1"}]},
            }
        },
    )

    assert observed.status == "complete"
    assert observed.missing_outputs == []
    assert "market_evidence" in observed.produced_outputs


def test_mcp_tool_is_valid_only_as_evidence() -> None:
    old = _decomposition([IntentTask(task_id="task_1", intent="portfolio_state")])
    trace = build_goal_planning_trace("推荐一个比现在更稳健的持仓，并说明为什么稳健", old)
    goal_dict = dict(trace["semantic_goal"])
    goal = UserGoal(**goal_dict)
    plan = plan_from_user_goal(goal)
    mcp_task = IntentTask(task_id="task_3", intent="mcp.local_financial_evidence.market_risk_summary")
    mcp_plan = TaskPlan(
        tasks=[plan.tasks[0], plan.tasks[1], mcp_task],
        dependencies={"task_1": [], "task_2": ["task_1"], "task_3": []},
        expected_outputs=goal.expected_outputs,
        completion_contract={"must_produce": goal.expected_outputs},
    )

    validation = validate_task_plan(goal, mcp_plan)

    assert validation.valid is True


def test_write_request_goes_to_approval_preview_not_commit() -> None:
    routed = route_agent_query("兆易创新仓位太高了，减半", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["semantic_goal"]["requires_write"] is True
    assert routed.intent == "one_time_position_operation"
    assert routed.parameters.get("query") or trace["semantic_goal"]["raw_message"]


def test_execute_without_pending_plan_is_blocked_by_validator() -> None:
    routed = route_agent_query("按这个方案执行", enable_llm=False)
    trace = routed.decomposition["diagnostics"]["phase10_goal_planning"]

    assert trace["semantic_goal"]["action"] == "prepare_execution_confirmation"
    assert trace["plan_validation"]["valid"] is False
    assert "write_request_missing_pending_plan" in trace["plan_validation"]["errors"]


def test_shadow_mode_records_old_and_new_decisions() -> None:
    routed = route_agent_query("推荐一个比现在更稳健的持仓，并说明为什么稳健", enable_llm=False)
    shadow = routed.decomposition["diagnostics"]["phase10_goal_planning"]["shadow_mode"]

    assert shadow["enabled"] is True
    assert shadow["old_tasks"]
    assert shadow["new_tasks"] == ["portfolio_state", "portfolio_risk", "ranking"]
    assert "validator_result" in shadow
