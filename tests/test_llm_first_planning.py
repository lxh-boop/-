from __future__ import annotations

import json

from agent.intent_decomposition import layered_decomposer
from agent.intent_decomposition import llm_decomposer
from agent.intent_decomposition.rule_fallback import decompose_with_rules, extract_rule_hints
from agent.intent_decomposition.schemas import IntentDecomposition, UserGoal


class FakeClient:
    responses: list[str] = []

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or "test-key"
        self.base_url = base_url or ""
        self.model = model or "test-model"

    def chat(self, messages, temperature=0.0, max_tokens=1000):
        assert messages
        if not self.responses:
            raise AssertionError("missing fake LLM response")
        return self.responses.pop(0)


def _risk_candidate() -> dict:
    return {
        "user_goal": {
            "raw_message": "分析当前组合风险",
            "goal_summary": "分析当前组合风险，不生成调仓建议",
            "action": "analyze",
            "objects": ["current_portfolio_risk"],
            "constraints": [],
            "expected_outputs": ["portfolio_risk", "risk_summary"],
            "follow_up": {"is_follow_up": False},
            "requires_current_state": True,
            "requires_external_evidence": False,
            "requires_write": False,
            "execution_requested": False,
            "missing_information": [],
            "need_clarification": False,
            "clarification_question": "",
            "confidence": 0.95,
            "reason_summary": "用户明确要求风险分析",
        },
        "task_plan": {
            "tasks": [
                {
                    "task_id": "task_1",
                    "intent": "portfolio_state",
                    "operation_type": "read",
                    "parameters": {"user_id_source": "$context.user_id"},
                    "depends_on": [],
                    "expected_outputs": ["current_portfolio"],
                    "confidence": 0.95,
                },
                {
                    "task_id": "task_2",
                    "intent": "portfolio_risk",
                    "operation_type": "read",
                    "parameters": {"user_id_source": "$context.user_id"},
                    "depends_on": ["task_1"],
                    "expected_outputs": ["portfolio_risk", "risk_summary"],
                    "confidence": 0.95,
                },
            ],
            "completion_contract": {"required_outputs": ["portfolio_risk", "risk_summary"]},
            "requires_write": False,
            "need_clarification": False,
            "confidence": 0.95,
        },
        "need_clarification": False,
        "confidence": 0.95,
    }


def test_rules_only_emit_hints_and_never_tasks():
    hints = extract_rule_hints("和现在的持仓做对比")
    values = {item.value for item in hints.hints}
    assert "compare" in values
    assert "portfolio" in values
    fallback = decompose_with_rules("查看当前持仓")
    assert fallback.tasks == []
    assert fallback.diagnostics["business_rule_fallback_disabled"] is True


def test_low_confidence_user_goal_requires_clarification():
    goal = UserGoal.from_dict({
        "action": "compare",
        "objects": ["portfolio"],
        "expected_outputs": ["comparison"],
        "confidence": 0.4,
    }, raw_message="和现在的持仓对比")
    assert goal.need_clarification is True
    assert goal.clarification_question


def test_planner_and_independent_reviewer_keep_risk_scope(monkeypatch):
    FakeClient.responses = [
        json.dumps(_risk_candidate(), ensure_ascii=False),
        json.dumps({
            "goal_review": {"status": "pass", "issues": [], "revised_user_goal": {}},
            "plan_review": {
                "status": "pass", "missing_tasks": [], "unexpected_tasks": [],
                "missing_outputs": [], "issues": [], "revised_task_plan": {},
            },
            "confidence": 0.96,
        }, ensure_ascii=False),
    ]
    monkeypatch.setattr(llm_decomposer, "LLMClient", FakeClient)
    result = llm_decomposer.decompose_with_llm(
        "分析当前组合风险",
        api_key="test-key",
        context={"user_id": "u1"},
        rule_hints=extract_rule_hints("分析当前组合风险").to_dict(),
    )
    assert [task.intent for task in result.tasks] == ["portfolio_state", "portfolio_risk"]
    assert "position_recommendation" not in {task.intent for task in result.tasks}
    assert result.user_goal is not None
    assert result.user_goal.action == "analyze"


def test_compare_without_reference_must_clarify(monkeypatch):
    candidate = {
        "user_goal": {
            "raw_message": "和现在的持仓做对比",
            "goal_summary": "比较未明确对象和当前持仓",
            "action": "clarify",
            "objects": ["current_portfolio"],
            "expected_outputs": [],
            "follow_up": {"is_follow_up": True, "reference_source": "missing"},
            "requires_current_state": True,
            "requires_write": False,
            "missing_information": ["comparison_reference"],
            "need_clarification": True,
            "clarification_question": "你希望把当前持仓与哪个方案、日期或组合进行比较？",
            "confidence": 0.55,
        },
        "task_plan": {
            "tasks": [],
            "completion_contract": {"required_outputs": []},
            "requires_write": False,
            "need_clarification": True,
            "clarification_question": "你希望把当前持仓与哪个方案、日期或组合进行比较？",
            "confidence": 0.55,
        },
        "need_clarification": True,
        "clarification_question": "你希望把当前持仓与哪个方案、日期或组合进行比较？",
        "confidence": 0.55,
    }
    FakeClient.responses = [
        json.dumps(candidate, ensure_ascii=False),
        json.dumps({
            "goal_review": {"status": "clarify", "issues": ["比较对象缺失"], "revised_user_goal": {}},
            "plan_review": {
                "status": "clarify", "missing_tasks": [], "unexpected_tasks": [],
                "missing_outputs": ["comparison_reference"], "issues": [], "revised_task_plan": {},
            },
            "need_clarification": True,
            "clarification_question": "你希望把当前持仓与哪个方案、日期或组合进行比较？",
            "confidence": 0.98,
        }, ensure_ascii=False),
    ]
    monkeypatch.setattr(llm_decomposer, "LLMClient", FakeClient)
    result = llm_decomposer.decompose_with_llm(
        "和现在的持仓做对比",
        api_key="test-key",
        context={"user_id": "u1", "previous_result_summary": ""},
        rule_hints=extract_rule_hints("和现在的持仓做对比").to_dict(),
    )
    assert result.need_clarification is True
    assert result.tasks == []
    assert "哪个" in result.clarification_question


def test_missing_api_key_does_not_use_business_rule_fallback(monkeypatch):
    monkeypatch.setattr(layered_decomposer, "_load_saved_llm_settings", lambda: {"api_key": "", "base_url": "", "model": ""})
    result = layered_decomposer.decompose_intent("查看当前持仓", llm_api_key=None)
    assert result.tasks == []
    assert result.diagnostics["business_rule_fallback_disabled"] is True
    assert result.diagnostics["error_code"] == "missing_api_key"
