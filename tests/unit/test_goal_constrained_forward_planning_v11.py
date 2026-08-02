from __future__ import annotations

import json
import sys
import types
from types import SimpleNamespace

# The historical source bundle used for isolated delivery validation omits this
# helper although the real project contains it. Keep the test importable here.
if "agent.context.token_budget" not in sys.modules:
    stub = types.ModuleType("agent.context.token_budget")
    stub.estimate_tokens = lambda value: max(1, len(str(value)) // 4)
    stub.truncate_text_to_tokens = lambda value, max_tokens: str(value)[: max(1, int(max_tokens)) * 4]
    sys.modules["agent.context.token_budget"] = stub

from agent.collaboration.agent_directory import AgentDirectory
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.models import (
    GraphAgentTask,
    GraphWorkerResult,
    ResultStatus,
)
from agent.collaboration.planner import CoordinatorPlanner

from tests.unit._forward_plan_helpers import decorate_forward_plan


def _account_raw_plan() -> dict:
    return {
        "goal_contract": {
            "goal_summary": "查看当前账户资金并生成报告",
            "desired_output_types": ["AccountStateResult", "FinalReport"],
            "completion_criteria": ["展示权威账户资金摘要"],
            "constraints": [],
            "side_effect_policy": {
                "allow_derived_writes": False,
                "allow_proposal": False,
                "allow_commit": False,
            },
        },
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
                "objective": "汇总账户资金摘要",
                "task_type": "write_report",
                "args": {"report_goal": "查看当前账户资金"},
                "inputs": {
                    "upstream_results": {
                        "from_task_id": "account",
                        "expected_output_type": "AccountStateResult",
                    }
                },
                "constraints": [],
                "expected_output_type": "FinalReport",
                "priority": 2,
            },
        ],
    }


def _initial_slots() -> list[str]:
    return ["user_request", "user_identity", "reply_language", "analysis_permission"]


def test_all_task_cards_expose_forward_information_semantics() -> None:
    for card in AgentDirectory().list_cards():
        for contract in card.task_contracts:
            assert contract.produces_information_slots
            assert contract.coverage_semantics
            assert contract.freshness_semantics
            assert contract.authority_level


def test_task_observation_distinguishes_failure_kinds() -> None:
    task = GraphAgentTask(
        task_id="t1",
        run_id="r",
        session_id="s",
        worker_id="W02",
        assigned_agent="PORTFOLIO_ANALYST",
        objective="查询账户",
        purpose="提供账户事实",
        why_selected="目标需要账户事实",
        task_type="query_account_state",
        user_id="cht",
        expected_output_type="AccountStateResult",
        expected_output={"information_slots": ["account_financial_state"]},
        completion_criteria=["返回账户事实"],
        failure_policy={},
        replan_triggers=["结果不足"],
    )

    empty = GraphWorkerResult(
        task_id="t1",
        agent_id="PORTFOLIO_ANALYST",
        status=ResultStatus.COMPLETED,
        output_type="AccountStateResult",
        data=None,
        summary="",
    )
    empty_obs = AgentCollaborationCoordinator._task_observation(task, empty)
    assert empty_obs["failure_kind"] == "business_result_empty"
    assert empty_obs["semantic_satisfied"] is True

    partial = GraphWorkerResult(
        task_id="t1",
        agent_id="PORTFOLIO_ANALYST",
        status=ResultStatus.PARTIAL,
        output_type="AccountStateResult",
        data={"cash": 1},
    )
    partial_obs = AgentCollaborationCoordinator._task_observation(task, partial)
    assert partial_obs["failure_kind"] == "business_result_insufficient"
    assert partial_obs["replan_recommended"] is True

    failed = GraphWorkerResult(
        task_id="t1",
        agent_id="PORTFOLIO_ANALYST",
        status=ResultStatus.FAILED,
        output_type="AccountStateResult",
        data=None,
        error={"code": "validation", "retryable": False},
    )
    failed_obs = AgentCollaborationCoordinator._task_observation(task, failed)
    assert failed_obs["failure_kind"] == "parameter_contract_failure"
    assert failed_obs["repairable"] is True

    need_context = GraphWorkerResult(
        task_id="t1",
        agent_id="PORTFOLIO_ANALYST",
        status=ResultStatus.NEED_CONTEXT,
        output_type="AccountStateResult",
        data=None,
    )
    context_obs = AgentCollaborationCoordinator._task_observation(task, need_context)
    assert context_obs["failure_kind"] == "context_missing"
    assert context_obs["replan_recommended"] is False


def test_forward_replan_freezes_success_and_adds_new_report() -> None:
    initial_payload = decorate_forward_plan(
        _account_raw_plan(),
        initial_slots=_initial_slots(),
        goal_slots=["account_financial_state", "user_facing_report"],
    )

    class InitialLLM:
        def generate_json(self, **kwargs):
            kwargs["validator"](initial_payload)
            return initial_payload

    planner = CoordinatorPlanner(AgentDirectory(), llm_service=InitialLLM())
    tasks, _ = planner.plan(
        query="查看当前账户资金",
        request_mode="analysis",
        session_id="s",
        run_id="r",
        user_id="cht",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
        language="zh",
        as_of_time="",
    )
    by_id = {task.task_id: task for task in tasks}
    results = {
        "account": GraphWorkerResult(
            task_id="account",
            agent_id=by_id["account"].assigned_agent,
            status=ResultStatus.COMPLETED,
            output_type="AccountStateResult",
            data={"cash": 100},
            summary="账户查询成功",
        ),
        "report": GraphWorkerResult(
            task_id="report",
            agent_id=by_id["report"].assigned_agent,
            status=ResultStatus.PARTIAL,
            output_type="FinalReport",
            data={"content": ""},
            summary="",
        ),
    }
    observations = AgentCollaborationCoordinator._build_task_observations(tasks, results)

    class ReplanLLM:
        def generate_json(self, **kwargs):
            request = json.loads(kwargs["messages"][1]["content"])
            frozen = request["frozen_reusable_tasks"]
            assert [row["task_id"] for row in frozen] == ["account"]
            raw = {
                "goal_contract": request["goal_contract"],
                "tasks": [
                    frozen[0],
                    {
                        "task_id": "report_repair_1",
                        "worker_id": "W06",
                        "objective": "重新汇总已验证的账户资金摘要",
                        "task_type": "write_report",
                        "args": {"report_goal": "查看当前账户资金"},
                        "inputs": {
                            "upstream_results": {
                                "from_task_id": "account",
                                "expected_output_type": "AccountStateResult",
                            }
                        },
                        "constraints": [],
                        "expected_output_type": "FinalReport",
                        "priority": 2,
                    },
                ],
            }
            candidate = decorate_forward_plan(
                raw,
                initial_slots=request["authoritative_initial_information_slots"],
                goal_slots=["account_financial_state", "user_facing_report"],
            )
            kwargs["validator"](candidate)
            return candidate

    planner.llm_service = ReplanLLM()
    full_tasks, new_tasks, meta = planner.replan_forward(
        query="查看当前账户资金",
        request_mode="analysis",
        session_id="s",
        run_id="r",
        user_id="cht",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
        language="zh",
        as_of_time="",
        current_tasks=tasks,
        current_results=results,
        observations=observations,
        replan_round=1,
    )

    assert [task.task_id for task in full_tasks] == ["account", "report_repair_1"]
    assert [task.task_id for task in new_tasks] == ["report_repair_1"]
    assert meta["reused_task_ids"] == ["account"]
    assert meta["planning_policy"] == "goal_constrained_forward_replanning"
