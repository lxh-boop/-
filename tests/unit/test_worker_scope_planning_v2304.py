from __future__ import annotations

import json

import pytest

from agent.capabilities import CapabilityRegistry
from agent.capabilities.validator import CapabilityPlanValidator
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_catalog import WorkerDescriptionCatalog
from agent.collaboration.worker_directory import CapabilityWorkerDirectory

from agent.collaboration.worker_directory import PORTFOLIO_ANALYST
from agent.tool_dag.planner import WorkerToolDagPlanner
from agent.tool_dag.validation import ToolDagValidator
from agent.tool_runtime import ToolRegistry
from agent.worker_tools.internal_system import (
    INTERNAL_PORTFOLIO_GET_STATE,
    INTERNAL_USER_PROFILE_GET,
    build_internal_system_tool_definitions,
)
from agent.worker_tools.registry import WorkerToolDirectory


class _ScopeToolDirectory:
    def semantic_output_slots(self, worker_role, *, tool_names=None):
        del tool_names
        if worker_role == "PORTFOLIO_ANALYST":
            return [
                "current_portfolio_state",
                "portfolio_positions",
                "account_financial_state",
                "user_profile_state",
                "user_constraints",
                "entity_model_signals",
                "market_ranking_signals",
                "model_quality_metrics",
                "backtest_summary",
                "selected_strategy_state",
            ]
        if worker_role == "EVIDENCE_COLLECTOR":
            return ["entity_external_evidence", "evidence_source_records"]
        return []


def _contract(*, inputs, outputs, rules, effect="read"):
    return {
        "description": "worker-scope contract",
        "required_inputs": [
            {"slot_id": slot, "required": True, "cardinality": "one", "required_paths": []}
            for slot in inputs
        ],
        "promised_outputs": [
            {"slot_id": slot, "provenance_required": True, "required_paths": []}
            for slot in outputs
        ],
        "acceptance_rule_ids": list(rules),
        "forbidden_output_slots": [],
        "criticality": "required",
        "effect_limit": effect,
    }


def test_main_agent_catalog_exposes_one_worker_scope_not_boundary_menu() -> None:
    rows = WorkerDescriptionCatalog(
        CapabilityWorkerDirectory(),
        CapabilityRegistry(),
        worker_tool_directory=_ScopeToolDirectory(),
    ).descriptions(request_mode="analysis")
    w02 = next(row for row in rows if row["worker_id"] == "W02")

    assert w02["capability_scope_mode"] == "worker_level"
    assert "supported_boundaries" not in w02
    assert "supported_boundary_ids" not in w02
    assert "current_portfolio_state" in w02["output_slot_examples"]
    assert "user_profile_state" in w02["output_slot_examples"]
    assert "user_constraints" in w02["output_slot_examples"]
    assert "portfolio.*" in w02["produced_output_patterns"]
    assert "profile.*" in w02["produced_output_patterns"]


def test_w02_single_worker_scope_can_cover_portfolio_and_user_context_outputs() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    payload = {
        "goal_contract": {
            "desired_outputs": [
                "current_portfolio_state",
                "portfolio_positions",
                "user_profile_state",
                "user_constraints",
            ],
            "required_information_slots": [],
            "effect_limit": "read",
        },
        "tasks": [{
            "task_id": "T01",
            "worker_id": "W02",
            "boundary_id": "system_internal_fact_provider",
            "objective": "读取当前持仓、用户画像和交易约束",
            "effect_limit": "read",
            "contracts": [_contract(
                inputs=["user_identity", "permission_context"],
                outputs=[
                    "current_portfolio_state",
                    "portfolio_positions",
                    "user_profile_state",
                    "user_constraints",
                ],
                rules=[
                    "schema_valid",
                    "provenance_present",
                    "business_empty_explicit",
                    "no_persistent_write",
                ],
            )],
        }],
    }
    tasks = validator.validate(
        payload,
        request_mode="analysis",
        initial_information_slots={"user_identity", "permission_context"},
    )
    assert tasks[0].worker_id == "W02"
    assert set(tasks[0].output_slots()) == {
        "current_portfolio_state",
        "portfolio_positions",
        "user_profile_state",
        "user_constraints",
    }


def test_worker_scope_still_rejects_cross_worker_semantic_output() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    payload = {
        "goal_contract": {
            "desired_outputs": ["entity_external_evidence"],
            "required_information_slots": [],
            "effect_limit": "read",
        },
        "tasks": [{
            "task_id": "T01",
            "worker_id": "W02",
            "boundary_id": "system_internal_fact_provider",
            "objective": "错误地产出外部证据",
            "effect_limit": "read",
            "contracts": [_contract(
                inputs=["user_identity"],
                outputs=["entity_external_evidence"],
                rules=["schema_valid", "provenance_present", "no_persistent_write"],
            )],
        }],
    }
    with pytest.raises(Exception, match="capability_output_semantic_outside_worker_scope"):
        validator.validate(
            payload,
            request_mode="analysis",
            initial_information_slots={"user_identity"},
        )


def test_session_summary_remains_context_not_w04_business_slot() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    payload = {
        "goal_contract": {
            "desired_outputs": ["portfolio_risk_result"],
            "required_information_slots": [],
            "effect_limit": "read",
        },
        "tasks": [{
            "task_id": "T01",
            "worker_id": "W04",
            "boundary_id": "portfolio_risk_assessment",
            "objective": "评估组合风险",
            "effect_limit": "read",
            "contracts": [_contract(
                inputs=["session_summary"],
                outputs=["portfolio_risk_result"],
                rules=["schema_valid", "provenance_present", "no_persistent_write"],
            )],
        }],
    }
    with pytest.raises(Exception, match="planner_context_used_as_business_input"):
        validator.validate(
            payload,
            request_mode="analysis",
            initial_information_slots={"session_summary"},
        )


def test_portfolio_adjustment_plans_one_broad_w02_worker_and_preserves_slot_binding() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.dag_prompt = None

        def generate_json(self, **kwargs):
            stage = kwargs["stage"]
            if stage == "upfront_user_intent_planning":
                payload = {
                    "intent_summary": "基于当前持仓、用户约束和组合风险形成待审批持仓调整建议",
                    "needs": [
                        {"description": "获取当前持仓、用户画像和交易约束", "required": True},
                        {"description": "评估当前组合风险", "required": True},
                        {"description": "形成待审批持仓调整方案", "required": True},
                    ],
                    "constraints": [],
                    "scope_note": "当前用户组合",
                    "effect_limit": "proposal",
                }
            elif stage == "upfront_worker_call_selection":
                payload = {
                    "worker_calls": [
                        {
                            "call_id": "WC01",
                            "worker_id": "W02",
                            "objective": "读取当前持仓、用户画像和交易约束",
                            "covers_need_ids": ["N01"],
                            "desired_output_slots": [
                                "current_portfolio_state",
                                "portfolio_positions",
                                "user_profile_state",
                                "user_constraints",
                            ],
                        },
                        {
                            "call_id": "WC02",
                            "worker_id": "W04",
                            "objective": "评估当前组合风险",
                            "covers_need_ids": ["N02"],
                            "desired_output_slots": [
                                "portfolio_risk_result",
                                "risk_constraint_review",
                                "analysis.risk",
                            ],
                        },
                        {
                            "call_id": "WC03",
                            "worker_id": "W05",
                            "objective": "形成待审批持仓调整方案",
                            "covers_need_ids": ["N03"],
                            "desired_output_slots": ["reviewed_proposal", "proposal.rebalance"],
                        },
                        {
                            "call_id": "WC04",
                            "worker_id": "W06",
                            "objective": "生成用户可读回答",
                            "covers_need_ids": ["N_FINAL"],
                            "desired_output_slots": ["user_facing_report", "goal_completion_summary"],
                        },
                    ],
                    "selection_reason": "W02一次读取内部用户与组合事实，后续Worker继续分析和形成Proposal。",
                }
            elif stage == "upfront_worker_dag_planning":
                self.dag_prompt = json.loads(kwargs["messages"][1]["content"])
                required_shape = self.dag_prompt["required_output_shape"]["tasks"][0]
                assert "boundary_id" not in required_shape
                assert "capability_boundary_catalog" not in self.dag_prompt
                assert all("supported_boundaries" not in row for row in self.dag_prompt["selected_worker_descriptions"])
                payload = {
                    "tasks": [
                        {
                            "worker_id": "W02",
                            "objective": "读取当前持仓、用户画像和交易约束",
                            "effect_limit": "read",
                            "priority": 1,
                            "business_parameters": {},
                            "contracts": [_contract(
                                inputs=["user_identity", "permission_context"],
                                outputs=[
                                    "current_portfolio_state",
                                    "portfolio_positions",
                                    "user_profile_state",
                                    "user_constraints",
                                ],
                                rules=[
                                    "schema_valid",
                                    "provenance_present",
                                    "business_empty_explicit",
                                    "no_persistent_write",
                                ],
                            )],
                        },
                        {
                            "worker_id": "W04",
                            "objective": "评估当前组合风险",
                            "effect_limit": "read",
                            "priority": 1,
                            "business_parameters": {},
                            "contracts": [_contract(
                                inputs=[
                                    "current_portfolio_state",
                                    "portfolio_positions",
                                    "user_profile_state",
                                    "user_constraints",
                                ],
                                outputs=[
                                    "portfolio_risk_result",
                                    "risk_constraint_review",
                                    "analysis.risk",
                                ],
                                rules=[
                                    "schema_valid",
                                    "provenance_present",
                                    "claims_traceable",
                                    "failure_kind_classified",
                                    "no_persistent_write",
                                ],
                            )],
                        },
                        {
                            "worker_id": "W05",
                            "objective": "形成待审批持仓调整方案",
                            "effect_limit": "proposal",
                            "priority": 1,
                            "business_parameters": {},
                            "contracts": [_contract(
                                inputs=[
                                    "current_portfolio_state",
                                    "portfolio_positions",
                                    "user_profile_state",
                                    "user_constraints",
                                    "portfolio_risk_result",
                                    "risk_constraint_review",
                                    "analysis.risk",
                                ],
                                outputs=["reviewed_proposal", "proposal.rebalance"],
                                rules=[
                                    "schema_valid",
                                    "claims_traceable",
                                    "proposal_requires_approval",
                                    "no_persistent_write",
                                    "goal_coverage",
                                ],
                                effect="proposal",
                            )],
                        },
                        {
                            "worker_id": "W06",
                            "objective": "生成用户可读回答",
                            "effect_limit": "read",
                            "priority": 1,
                            "business_parameters": {},
                            "contracts": [_contract(
                                inputs=["reviewed_proposal", "portfolio_risk_result"],
                                outputs=["user_facing_report", "goal_completion_summary"],
                                rules=[
                                    "schema_valid",
                                    "claims_traceable",
                                    "goal_coverage",
                                    "no_persistent_write",
                                ],
                            )],
                        },
                    ]
                }
            else:
                raise AssertionError(stage)
            kwargs["validator"](payload)
            return payload

    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=FakeLLM(),
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, metadata = planner.plan(
        query="你觉得我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s",
        run_id="r",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="上一轮分析了贵州茅台。",
    )

    assert [task.worker_id for task in tasks] == ["W02", "W04", "W05", "W06"]
    assert tasks[0].boundary_id == "system_internal_fact_provider"
    assert set(tasks[0].expected_output_slots) == {
        "current_portfolio_state",
        "portfolio_positions",
        "user_profile_state",
        "user_constraints",
    }
    assert tasks[1].dependency_task_ids == ["T01"]
    assert set(tasks[1].expected_output_slots) == {
        "portfolio_risk_result",
        "risk_constraint_review",
        "analysis.risk",
    }
    assert "session_summary" not in {
        row["input_slot_id"]
        for row in metadata["assignment_audit"][1]["input_bindings"]
    }
    assert metadata["capability_scope_mode"] == "worker_level"


def test_w02_broad_scope_private_tool_dag_reuses_existing_tool_io_contracts() -> None:
    class FakeIdentity:
        pass

    class FakeProvider:
        identity = FakeIdentity()

        def public_entity_descriptor(self, ref):
            return {}

    registry = ToolRegistry(build_internal_system_tool_definitions(FakeProvider()))
    directory = WorkerToolDirectory(registry)
    validator = ToolDagValidator(registry, directory)

    # 直接使用现有 W02 私有 Tool 合同，确认无需新增 Tool 传输协议。
    portfolio_tool = registry.get(INTERNAL_PORTFOLIO_GET_STATE)
    profile_tool = registry.get(INTERNAL_USER_PROFILE_GET)
    assert {item.slot_id for item in portfolio_tool.output_contracts} == {
        "current_portfolio_state",
        "portfolio_positions",
    }
    assert {item.slot_id for item in profile_tool.output_contracts} == {
        "user_profile_state",
        "user_constraints",
    }

    class FakeLLM:
        def generate_json(self, **kwargs):
            assert kwargs["stage"] == "worker_private_tool_dag_planner"
            payload = {
                "tasks": [
                    {
                        "tool_task_id": "P01",
                        "tool_name": INTERNAL_PORTFOLIO_GET_STATE,
                        "objective": "读取当前组合和持仓",
                        "args": {},
                        "inputs": {"user_id": {"from_context": "user_id"}},
                        "priority": 1,
                    },
                    {
                        "tool_task_id": "P02",
                        "tool_name": INTERNAL_USER_PROFILE_GET,
                        "objective": "读取用户画像和约束",
                        "args": {},
                        "inputs": {"user_id": {"from_context": "user_id"}},
                        "priority": 1,
                    },
                ],
                "final_output_task_ids": ["P01", "P02"],
            }
            kwargs["validator"](payload)
            return payload

    planner = WorkerToolDagPlanner(
        llm_service=FakeLLM(),
        directory=directory,
        validator=validator,
    )
    plan = planner.plan(
        worker_task_id="T01",
        worker_role=PORTFOLIO_ANALYST,
        worker_objective="一次读取当前持仓、用户画像和交易约束",
        # 仅保留为兼容/审计字段；MainAgent 不再选择细能力。
        boundary_id="system_internal_fact_provider",
        worker_prompt="在W02整体专业能力范围内自主规划私有Tool DAG",
        available_context={"user_id": "u"},
        required_output_keys=[
            "current_portfolio_state",
            "portfolio_positions",
            "user_profile_state",
            "user_constraints",
        ],
        completion_criteria=["schema_valid", "provenance_present"],
        allowed_tool_names=[INTERNAL_PORTFOLIO_GET_STATE, INTERNAL_USER_PROFILE_GET],
        run_id="run",
        read_only=True,
    )
    assert [task.tool_name for task in plan.tasks] == [
        INTERNAL_PORTFOLIO_GET_STATE,
        INTERNAL_USER_PROFILE_GET,
    ]
    assert plan.tasks[0].inputs["user_id"] == {"from_context": "user_id"}
    assert plan.tasks[1].inputs["user_id"] == {"from_context": "user_id"}
