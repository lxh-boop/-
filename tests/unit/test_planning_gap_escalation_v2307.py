from __future__ import annotations

from agent.capabilities import CapabilityRegistry
from agent.capabilities.models import CapabilityTask
from agent.capabilities.slot_binder import SlotBinder
from agent.collaboration.models import MissingContextItem
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.worker_directory import CapabilityWorkerDirectory
from agent.context.context_sufficiency_gate import ContextAndEntitySufficiencyGate


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
                "market_ranking_signals",
            ]
        return []


def _contract(inputs, outputs, rules, effect="read"):
    return {
        "description": "v2307 contract",
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


def test_w04_w05_public_descriptions_are_slot_driven_not_worker_bound() -> None:
    directory = CapabilityWorkerDirectory()
    w04 = directory.get("W04")
    w05 = directory.get("W05")

    assert "信息Slot" in w04.full_description
    assert "不是固定依赖某个Worker" in w04.full_description
    assert "上报缺失信息" in w04.full_description
    assert "不与W04或任何特定Worker ID硬绑定" in w05.full_description
    assert "风险" in w05.full_description


def test_slot_binder_reports_all_missing_required_slots_as_structured_planning_gap() -> None:
    tasks = [
        CapabilityTask.from_dict({
            "task_id": "T01",
            "worker_id": "W04",
            "boundary_id": "portfolio_risk_assessment",
            "objective": "评估风险",
            "effect_limit": "read",
            "contracts": [_contract(
                ["current_portfolio_state", "portfolio_positions", "user_constraints"],
                ["portfolio_risk_result"],
                ["schema_valid", "provenance_present", "claims_traceable", "no_persistent_write"],
            )],
        }, task_id="T01"),
    ]

    try:
        SlotBinder().bind(tasks, initial_information_slots={"user_identity"})
    except WorkerContractViolation as exc:
        assert exc.code == "capability_required_input_has_no_producer"
        assert exc.detail == "current_portfolio_state"
        gaps = exc.metadata["planning_gaps"]
        assert {row["input_slot_id"] for row in gaps} == {
            "current_portfolio_state",
            "portfolio_positions",
            "user_constraints",
        }
        assert {row["consumer_worker_id"] for row in gaps} == {"W04"}
        assert {row["repair_scope"] for row in gaps} == {"worker_selection"}
    else:
        raise AssertionError("missing producer planning gap was not raised")


def test_main_agent_repairs_missing_producer_without_hard_binding_w04_to_w02() -> None:
    class FakeLLM:
        def __init__(self):
            self.stages = []
            self.gap_payload = None

        def generate_json(self, **kwargs):
            stage = kwargs["stage"]
            self.stages.append(stage)
            if stage == "upfront_user_intent_planning":
                payload = {
                    "intent_summary": "分析当前组合风险并给出调仓方案。",
                    "needs": [
                        {"description": "分析当前组合风险", "required": True},
                        {"description": "形成调仓方案", "required": True},
                    ],
                    "constraints": [],
                    "scope_note": "当前整体组合",
                    "effect_limit": "proposal",
                }
            elif stage == "upfront_worker_call_selection":
                # 故意复现真实 Run：MainAgent 初次漏选 W02。
                payload = {
                    "worker_calls": [
                        {"call_id": "WC01", "worker_id": "W04", "objective": "评估组合风险", "covers_need_ids": ["N01"], "desired_output_slots": ["portfolio_risk_result"]},
                        {"call_id": "WC02", "worker_id": "W05", "objective": "形成调仓方案", "covers_need_ids": ["N02"], "desired_output_slots": ["reviewed_proposal"]},
                        {"call_id": "WC03", "worker_id": "W06", "objective": "生成最终回答", "covers_need_ids": ["N_FINAL"], "desired_output_slots": ["user_facing_report"]},
                    ],
                    "selection_reason": "初次仅选择业务分析、方案和报告能力。",
                }
            elif stage == "upfront_worker_dag_planning":
                payload = {
                    "tasks": [
                        {
                            "worker_id": "W04", "objective": "评估组合风险", "effect_limit": "read", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["current_portfolio_state", "portfolio_positions", "user_constraints"],
                                ["portfolio_risk_result"],
                                ["schema_valid", "provenance_present", "claims_traceable", "no_persistent_write"],
                            )],
                        },
                        {
                            "worker_id": "W05", "objective": "形成调仓方案", "effect_limit": "proposal", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["current_portfolio_state", "portfolio_risk_result"],
                                ["reviewed_proposal"],
                                ["schema_valid", "claims_traceable", "proposal_requires_approval", "no_persistent_write", "goal_coverage"],
                                effect="proposal",
                            )],
                        },
                        {
                            "worker_id": "W06", "objective": "生成最终回答", "effect_limit": "read", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["reviewed_proposal"],
                                ["user_facing_report"],
                                ["schema_valid", "claims_traceable", "goal_coverage", "no_persistent_write"],
                            )],
                        },
                    ]
                }
            elif stage == "planning_gap_worker_call_repair":
                user_payload = kwargs["messages"][1]["content"]
                self.gap_payload = user_payload
                payload = {
                    "worker_calls": [
                        {"call_id": "WC01", "worker_id": "W02", "objective": "读取当前组合与用户约束权威事实", "covers_need_ids": [], "desired_output_slots": ["current_portfolio_state", "portfolio_positions", "user_constraints"]},
                        {"call_id": "WC02", "worker_id": "W04", "objective": "评估组合风险", "covers_need_ids": ["N01"], "desired_output_slots": ["portfolio_risk_result"]},
                        {"call_id": "WC03", "worker_id": "W05", "objective": "形成调仓方案", "covers_need_ids": ["N02"], "desired_output_slots": ["reviewed_proposal"]},
                        {"call_id": "WC04", "worker_id": "W06", "objective": "生成最终回答", "covers_need_ids": ["N_FINAL"], "desired_output_slots": ["user_facing_report"]},
                    ],
                    "selection_reason": "根据Planning Gap增加能够生产缺失Slot的内部事实能力，保留原业务Worker。",
                }
            elif stage == "recovery_worker_dag_planning":
                payload = {
                    "tasks": [
                        {
                            "worker_id": "W02", "objective": "读取当前组合与用户约束权威事实", "effect_limit": "read", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["user_identity", "permission_context"],
                                ["current_portfolio_state", "portfolio_positions", "user_constraints"],
                                ["schema_valid", "provenance_present", "business_empty_explicit", "no_persistent_write"],
                            )],
                        },
                        {
                            "worker_id": "W04", "objective": "评估组合风险", "effect_limit": "read", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["current_portfolio_state", "portfolio_positions", "user_constraints"],
                                ["portfolio_risk_result"],
                                ["schema_valid", "provenance_present", "claims_traceable", "no_persistent_write"],
                            )],
                        },
                        {
                            "worker_id": "W05", "objective": "形成调仓方案", "effect_limit": "proposal", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["current_portfolio_state", "portfolio_risk_result"],
                                ["reviewed_proposal"],
                                ["schema_valid", "claims_traceable", "proposal_requires_approval", "no_persistent_write", "goal_coverage"],
                                effect="proposal",
                            )],
                        },
                        {
                            "worker_id": "W06", "objective": "生成最终回答", "effect_limit": "read", "priority": 1, "business_parameters": {},
                            "contracts": [_contract(
                                ["reviewed_proposal"],
                                ["user_facing_report"],
                                ["schema_valid", "claims_traceable", "goal_coverage", "no_persistent_write"],
                            )],
                        },
                    ]
                }
            else:
                raise AssertionError(stage)
            kwargs["validator"](payload)
            return payload

    llm = FakeLLM()
    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=llm,
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, metadata = planner.plan(
        query="你认为我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s",
        run_id="r",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )

    assert [task.worker_id for task in tasks] == ["W02", "W04", "W05", "W06"]
    assert tasks[1].dependency_task_ids == ["T01"]
    assert set(tasks[2].dependency_task_ids) == {"T01", "T02"}
    assert metadata["planning_gap_repair"]["repair_count"] == 1
    assert llm.stages == [
        "upfront_user_intent_planning",
        "upfront_worker_call_selection",
        "upfront_worker_dag_planning",
        "planning_gap_worker_call_repair",
        "recovery_worker_dag_planning",
    ]
    # 代码没有 W04->W02 硬绑定；MainAgent只看到缺失Slot和公开能力候选。
    assert "planning_gap_context" in (llm.gap_payload or "")
    assert "current_portfolio_state" in (llm.gap_payload or "")


def test_context_sufficiency_asks_user_only_for_explicit_parameter_gap() -> None:
    gate = ContextAndEntitySufficiencyGate()
    internal = gate.evaluate(missing_items=[MissingContextItem(
        key="current_portfolio_state",
        description="Worker required Slot is unavailable",
        reason="worker_input_slot_unresolved: internal Slot gap",
    )])
    assert internal.next_action == "wait_context"
    assert internal.missing_parameters == []
    assert internal.missing_context_slots == ["current_portfolio_state"]

    user_parameter = gate.evaluate(missing_items=[MissingContextItem(
        key="comparison_security_b",
        description="缺少第二只比较股票",
        reason="parameter missing: user must specify the second security",
    )])
    assert user_parameter.next_action == "ask_user"
    assert user_parameter.missing_parameters == ["comparison_security_b"]


def test_worker_escalation_marks_only_declared_parameter_gap_as_user_input_required() -> None:
    from types import SimpleNamespace

    from agent.collaboration.error_contracts import escalation_from_worker_result

    task = SimpleNamespace(objective="比较证券", boundary_id="entity.analysis")
    parameter_result = SimpleNamespace(
        status=SimpleNamespace(value="need_context"),
        error=None,
        missing_items=[MissingContextItem(
            key="comparison_security_b",
            description="缺少第二只证券",
            reason="parameter missing: user must specify",
        )],
        summary="需要用户补充参数",
    )
    internal_result = SimpleNamespace(
        status=SimpleNamespace(value="need_context"),
        error=None,
        missing_items=[MissingContextItem(
            key="current_portfolio_state",
            description="缺少内部组合状态",
            reason="worker_input_slot_unresolved: internal Slot gap",
        )],
        summary="需要内部上下文",
    )

    assert escalation_from_worker_result(task, parameter_result).error_id == "user_input_required"
    assert escalation_from_worker_result(task, internal_result).error_id == "worker_context_unresolved"
