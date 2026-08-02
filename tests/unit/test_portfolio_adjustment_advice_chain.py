from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.collaboration.agent_directory import AgentDirectory, STRATEGY_GUARD, W05
from agent.collaboration.entry_decision import MainEntryDecisionPlanner, RequestMode
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_contracts import WorkerContractViolation

from tests.unit._forward_plan_helpers import decorate_forward_plan


def _ref(task_id: str, output_type: str) -> dict[str, str]:
    return {"from_task_id": task_id, "expected_output_type": output_type}


def _goal(
    *output_types: str,
    proposal: bool = False,
    derived_writes: bool = False,
) -> dict[str, Any]:
    return {
        "goal_summary": "完成用户明确提出的目标并生成最终报告",
        "desired_output_types": list(dict.fromkeys([*output_types, "FinalReport"])),
        "completion_criteria": ["返回目标所需的专业结果和最终报告"],
        "constraints": [],
        "side_effect_policy": {
            "allow_derived_writes": derived_writes,
            "allow_proposal": proposal,
            "allow_commit": False,
        },
    }


def _strategy_proposal_plan() -> dict[str, Any]:
    """A valid proposal plan that is deliberately not a portfolio chain."""

    plan = {
        "goal_contract": _goal(
            "SelectedStrategyResult",
            "ReviewedProposal",
            proposal=True,
        ),
        "tasks": [
            {
                "task_id": "strategy_state",
                "worker_id": "W02",
                "objective": "读取当前选定策略作为审查基线",
                "task_type": "query_selected_strategy",
                "args": {},
                "inputs": {},
                "constraints": [],
                "expected_output_type": "SelectedStrategyResult",
                "priority": 1,
            },
            {
                "task_id": "strategy_review",
                "worker_id": "W05",
                "objective": "审查当前策略并形成待审批变更预案",
                "task_type": "review_strategy",
                "args": {
                    "change_intent": "把当前策略调整得更稳健",
                    "proposal_constraints": ["不得直接执行"],
                },
                "inputs": {
                    "current_strategy": _ref(
                        "strategy_state", "SelectedStrategyResult"
                    )
                },
                "constraints": [],
                "expected_output_type": "ReviewedProposal",
                "priority": 2,
            },
            {
                "task_id": "report",
                "worker_id": "W06",
                "objective": "汇总策略审查和待审批方案",
                "task_type": "write_report",
                "args": {
                    "report_goal": "说明当前策略如何调整并展示待审批方案",
                    "reply_language": "zh",
                },
                "inputs": {
                    "upstream_results": [
                        _ref("strategy_state", "SelectedStrategyResult"),
                        _ref("strategy_review", "ReviewedProposal"),
                    ]
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 3,
            },
        ],
    }
    return decorate_forward_plan(
        plan,
        initial_slots=[
            "user_request",
            "user_identity",
            "reply_language",
            "explicit_change_intent",
            "proposal_permission",
        ],
        goal_slots=[
            "selected_strategy_state",
            "reviewed_proposal",
            "user_facing_report",
        ],
    )


def test_w05_card_is_detailed_and_remains_proposal_only() -> None:
    card = AgentDirectory().get(W05)
    contracts = {item.task_type: item for item in card.task_contracts}

    assert card.agent_id == STRATEGY_GUARD
    assert set(card.accepted_task_types) == {
        "review_strategy",
        "build_proposal",
        "review_proposal",
    }
    assert "recommend_adjustment" not in card.accepted_task_types
    assert card.output_types == ["ReviewedProposal"]
    assert card.side_effects == ["proposal_only"]
    assert card.can_generate_proposal is True

    build = contracts["build_proposal"]
    assert build.allowed_request_modes == ["proposal"]
    assert build.user_goal_examples
    assert build.negative_goal_examples
    assert build.completion_criteria
    assert build.planning_notes
    assert build.side_effect_policy["execution_allowed"] is False
    assert set(build.upstream_input_bindings) == {
        "current_state",
        "risk_constraints",
        "supporting_analysis",
    }

    review_strategy = contracts["review_strategy"]
    assert review_strategy.upstream_input_bindings["current_strategy"][
        "accepted_output_types"
    ] == ["SelectedStrategyResult"]

    review_proposal = contracts["review_proposal"]
    assert review_proposal.upstream_input_bindings["existing_proposal"][
        "accepted_output_types"
    ] == ["ReviewedProposal"]


def test_every_worker_exposes_detailed_task_contracts() -> None:
    directory = AgentDirectory()

    for card in directory.list_cards():
        assert card.description
        assert card.responsibility
        assert card.task_contracts, card.worker_id
        assert set(card.accepted_task_types) == {
            item.task_type for item in card.task_contracts
        }
        for contract in card.task_contracts:
            assert contract.description, (card.worker_id, contract.task_type)
            assert contract.output_type, (card.worker_id, contract.task_type)
            assert contract.selection_requirements, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.user_goal_examples, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.negative_goal_examples, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.completion_criteria, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.planning_notes, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.produces_information_slots, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.coverage_semantics, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.freshness_semantics, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.authority_level, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.allowed_request_modes, (
                card.worker_id,
                contract.task_type,
            )
            assert contract.side_effect_policy, (
                card.worker_id,
                contract.task_type,
            )


def test_planning_catalog_is_detailed_but_excludes_private_and_full_result_schema() -> None:
    catalog = AgentDirectory().planning_catalog()
    rendered = str(catalog)

    assert "private_tool_ids" not in rendered
    assert "private_worker_prompt" not in rendered
    assert "output_schema" not in rendered
    assert "user_goal_examples" in rendered
    assert "negative_goal_examples" in rendered
    assert "completion_criteria" in rendered
    assert "planning_notes" in rendered
    assert "consumes_information_slots" in rendered
    assert "produces_information_slots" in rendered
    assert "coverage_semantics" in rendered
    assert "freshness_semantics" in rendered
    assert "authority_level" in rendered
    assert len(rendered) < 100_000


def test_entry_decision_has_no_keyword_override_after_llm_decision() -> None:
    captured: dict[str, Any] = {}

    class FakeLLM:
        def generate_json(self, **kwargs):
            captured.update(kwargs)
            return {
                "mode": "analysis",
                "reason": "测试返回",
                "reply_language": "zh",
                "confidence": 0.8,
            }

    decision = MainEntryDecisionPlanner(llm_service=FakeLLM()).decide(
        query="你认为我的持仓应该怎么调整？",
        memory_summary="",
        execution_context={},
        language="zh",
    )

    # 入口不再使用关键词正则覆盖 LLM；正确分类由改进后的语义 Prompt 负责。
    assert decision.mode == RequestMode.ANALYSIS
    assert decision.source == "main_coordinator_llm"
    system_prompt = captured["messages"][0]["content"]
    assert "最终业务目标" in system_prompt
    assert "具体调仓方案" in system_prompt
    assert "W05" not in system_prompt


def test_generic_validator_accepts_non_portfolio_proposal_composition() -> None:
    planner = CoordinatorPlanner(AgentDirectory(), llm_service=SimpleNamespace())

    planner._validate_payload(
        _strategy_proposal_plan(),
        request_mode="proposal",
        authoritative_ref_ids=set(),
        authoritative_user_id="cht",
        reply_language="zh",
        user_request="把当前策略调整得更稳健",
    )


def test_generic_validator_rejects_missing_task_contract_input() -> None:
    plan = _strategy_proposal_plan()
    proposal = next(
        row for row in plan["tasks"] if row["task_type"] == "review_strategy"
    )
    proposal["inputs"] = {}

    with pytest.raises(WorkerContractViolation) as exc:
        CoordinatorPlanner(
            AgentDirectory(), llm_service=SimpleNamespace()
        )._validate_payload(
            plan,
            request_mode="proposal",
            authoritative_ref_ids=set(),
            authoritative_user_id="cht",
            reply_language="zh",
        )

    assert "required_upstream_input_missing" in str(exc.value)


def test_generic_validator_rejects_goal_output_without_producer() -> None:
    plan = _strategy_proposal_plan()
    plan["goal_contract"]["desired_output_types"].append("PortfolioRiskResult")

    with pytest.raises(WorkerContractViolation) as exc:
        CoordinatorPlanner(
            AgentDirectory(), llm_service=SimpleNamespace()
        )._validate_payload(
            plan,
            request_mode="proposal",
            authoritative_ref_ids=set(),
            authoritative_user_id="cht",
            reply_language="zh",
        )

    assert "goal_output_not_produced" in str(exc.value)


def test_planner_prompt_uses_goal_constrained_forward_planning_without_fixed_worker_chain() -> None:
    captured: dict[str, Any] = {}

    class FakeLLM:
        def generate_json(self, **kwargs):
            captured.update(kwargs)
            raw = {
                "goal_contract": _goal("AccountStateResult"),
                "tasks": [
                    {
                        "task_id": "account",
                        "worker_id": "W02",
                        "objective": "读取当前账户资金摘要",
                        "task_type": "query_account_state",
                        "args": {},
                        "inputs": {},
                        "constraints": [],
                        "expected_output_type": "AccountStateResult",
                        "priority": 1,
                    },
                    {
                        "task_id": "report",
                        "worker_id": "W06",
                        "objective": "汇总账户资金状态",
                        "task_type": "write_report",
                        "args": {"report_goal": "查看当前账户资金"},
                        "inputs": {
                            "upstream_results": _ref(
                                "account", "AccountStateResult"
                            )
                        },
                        "constraints": [],
                        "expected_output_type": "FinalReport",
                        "priority": 2,
                    },
                ],
            }
            request_payload = __import__("json").loads(
                kwargs["messages"][1]["content"]
            )
            payload = decorate_forward_plan(
                raw,
                initial_slots=request_payload[
                    "authoritative_initial_information_slots"
                ],
                goal_slots=["account_financial_state", "user_facing_report"],
            )
            kwargs["validator"](payload)
            return payload

    tasks, info = CoordinatorPlanner(
        AgentDirectory(), llm_service=FakeLLM()
    ).plan(
        query="查看当前账户资金",
        request_mode="analysis",
        session_id="session-1",
        run_id="run-1",
        user_id="cht",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
        language="zh",
        as_of_time="",
    )

    system_prompt = captured["messages"][0]["content"]
    assert "目标约束的正向扩展" in system_prompt
    assert "禁止使用预设业务链路" in system_prompt
    assert "不使用反向递归" in system_prompt
    assert "semantic role" in system_prompt
    assert "根任务写 inputs={}" in system_prompt
    assert "不得自行补造证券代码" in system_prompt
    assert captured["repair_mode"] == "targeted"
    request_payload = __import__("json").loads(
        captured["messages"][1]["content"]
    )
    examples = request_payload["planner_contract_examples"]
    assert examples["root_task_inputs"]["inputs"] == {}
    assert examples["single_upstream_input"]["inputs"]["current_state"][
        "from_task_id"
    ] == "T01"
    assert "from_task_id" in examples["invalid_unwrapped_reference"]["inputs"]
    assert "query_portfolio_state" not in system_prompt
    assert "build_proposal" not in system_prompt
    assert "W02" not in system_prompt
    assert "W05" not in system_prompt
    assert [task.task_type for task in tasks] == [
        "query_account_state",
        "write_report",
    ]
    assert info["planning_policy"] == "goal_constrained_forward_planning"
    assert info["task_expectations_generated"] is True
    assert all(task.expected_output for task in tasks)
    assert all(task.completion_criteria for task in tasks)
