from __future__ import annotations

from agent.capabilities import CapabilityContract, CapabilityRegistry, NeedRequirementCompiler
from agent.collaboration.planner import CoordinatorPlanner
from agent.collaboration.worker_contracts import WorkerContractViolation
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


class _ScopeToolDirectory:
    def semantic_output_slots(self, worker_role, *, tool_names=None):
        del tool_names
        if worker_role == "PORTFOLIO_ANALYST":
            return [
                "current_portfolio_state",
                "portfolio_positions",
                "user_profile_state",
                "user_constraints",
                "entity_model_signals",
                "market_ranking_signals",
            ]
        return []


class _RecommendationLLM:
    def __init__(self) -> None:
        self.stages: list[str] = []
        self.third_payload = None

    def generate_json(self, **kwargs):
        stage = kwargs["stage"]
        self.stages.append(stage)
        if stage == "upfront_user_intent_planning":
            payload = {
                "requirement_contract_version": "need-requirement.v1",
                "intent_summary": "读取当前组合和用户约束，并由系统形成待审批调仓建议。",
                "needs": [
                    {
                        "description": "获取当前组合状态与持仓",
                        "required": True,
                        "requirements": [
                            {"semantic_key": "portfolio_state", "direction": "output", "required": True},
                            {"semantic_key": "portfolio_positions", "direction": "output", "required": True},
                        ],
                    },
                    {
                        "description": "获取用户投资约束和画像",
                        "required": True,
                        "requirements": [
                            {"semantic_key": "user_constraints", "direction": "output", "required": True},
                            {"semantic_key": "user_profile", "direction": "output", "required": True},
                        ],
                    },
                    {
                        "description": "基于当前组合与用户约束形成系统推荐的调仓方案",
                        "required": True,
                        "requirements": [
                            {"semantic_key": "portfolio_state", "direction": "input", "required": True},
                            {"semantic_key": "portfolio_positions", "direction": "input", "required": True},
                            {"semantic_key": "user_constraints", "direction": "input", "required": True},
                            {"semantic_key": "user_profile", "direction": "input", "required": True},
                            {"semantic_key": "rebalance_proposal", "direction": "output", "required": True},
                            {"semantic_key": "rebalance_instructions", "direction": "output", "required": True},
                        ],
                    },
                ],
                "constraints": [],
                "scope_note": "当前完整投资组合",
                "effect_limit": "proposal",
            }
        elif stage == "upfront_worker_call_selection":
            payload = {
                "worker_calls": [
                    {
                        "call_id": "WC01",
                        "worker_id": "W02",
                        "objective": "读取当前组合和用户约束",
                        "covers_need_ids": ["N01", "N02"],
                        "desired_output_slots": [
                            "current_portfolio_state",
                            "portfolio_positions",
                            "user_constraints",
                            "user_profile_state",
                        ],
                    },
                    {
                        "call_id": "WC02",
                        "worker_id": "W05",
                        "objective": "形成待审批调仓建议",
                        "covers_need_ids": ["N03"],
                        "desired_output_slots": ["reviewed_proposal", "proposal.rebalance"],
                    },
                    {
                        "call_id": "WC03",
                        "worker_id": "W06",
                        "objective": "生成最终用户报告",
                        "covers_need_ids": ["N_FINAL"],
                        "desired_output_slots": ["user_facing_report"],
                    },
                ],
                "selection_reason": "内部事实->方案->报告",
            }
        elif stage == "upfront_worker_dag_planning":
            # V23.0.10: the third LLM no longer repeats full CapabilityContract.
            payload = {
                "task_requirements": [
                    {"call_id": "WC01", "requirement_ids": [], "additional_required_slots": []},
                    {
                        "call_id": "WC02",
                        "requirement_ids": ["N03-R01", "N03-R02", "N03-R03", "N03-R04"],
                        "additional_required_slots": [],
                    },
                    {
                        "call_id": "WC03",
                        "requirement_ids": [],
                        "additional_required_slots": ["reviewed_proposal", "proposal.rebalance"],
                    },
                ]
            }
            self.third_payload = kwargs["messages"][1]["content"]
        else:
            raise AssertionError(stage)
        kwargs["validator"](payload)
        return payload


def test_recommendation_need_compiles_target_weight_as_output_not_user_parameter() -> None:
    llm = _RecommendationLLM()
    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=llm,
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, metadata = planner.plan(
        query="你认为我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s-v2310",
        run_id="r-v2310",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )

    assert llm.stages == [
        "upfront_user_intent_planning",
        "upfront_worker_call_selection",
    ]
    assert [task.worker_id for task in tasks] == ["W02", "W05", "W06"]
    w05 = tasks[1]
    assert w05.dependency_task_ids == ["T01"]
    w05_contract = CapabilityContract.from_dict(w05.contracts[0])
    assert w05_contract.required_parameters == []
    assert set(w05_contract.input_slots(required_only=True)) == {
        "current_portfolio_state", "portfolio_positions", "user_constraints", "user_profile_state"
    }
    assert set(w05.expected_output_slots) == {"reviewed_proposal", "proposal.rebalance"}
    assert tasks[2].dependency_task_ids == ["T02"]
    assert metadata["capability_plan"]["contract_expansion_mode"] == "deterministic_need_worker_dag_compiler"
    assert llm.third_payload is None
    from agent.console_trace import reset_flow_context
    reset_flow_context()


def test_target_allocation_is_user_parameter_only_when_canonical_need_declares_it() -> None:
    registry = CapabilityRegistry()
    compiler = NeedRequirementCompiler(registry, CapabilityWorkerDirectory())
    target = compiler.normalize_requirement(
        {"semantic_key": "target_allocation", "direction": "parameter", "required": True},
        need_id="N01",
        index=0,
    )
    intent = {
        "needs": [{
            "need_id": "N01",
            "required": True,
            "requirements": [
                target,
                compiler.normalize_requirement(
                    {"semantic_key": "portfolio_state", "direction": "input", "required": True},
                    need_id="N01", index=1,
                ),
                compiler.normalize_requirement(
                    {"semantic_key": "entity_analysis", "direction": "input", "required": True},
                    need_id="N01", index=2,
                ),
                compiler.normalize_requirement(
                    {"semantic_key": "portfolio_risk", "direction": "output", "required": True},
                    need_id="N01", index=3,
                ),
            ],
        }]
    }
    tasks = compiler.expand_compact_tasks(
        intent_contract=intent,
        worker_calls=[{
            "call_id": "WC01", "worker_id": "W04", "covers_need_ids": ["N01"],
            "objective": "按用户指定配置比例评估组合风险",
            "desired_output_slots": ["portfolio_risk_result"],
        }],
        task_requirements=[{
            "call_id": "WC01",
            "requirement_ids": ["N01-R01", "N01-R02", "N01-R03"],
            "additional_required_slots": [],
        }],
        initial_slots={"current_portfolio_state", "entity_analysis"},
        request_mode="analysis",
    )
    parameter = tasks[0]["contracts"][0]["required_parameters"][0]
    assert parameter["parameter_id"] == "target_asset_allocation"
    assert parameter["source_policy"] == "user"
    assert "target_weight" in parameter["satisfy_by"]


def test_unknown_semantic_requirement_is_rejected_before_worker_selection() -> None:
    compiler = NeedRequirementCompiler(CapabilityRegistry(), CapabilityWorkerDirectory())
    try:
        compiler.normalize_requirement(
            {"semantic_key": "predict_user_lifetime_wealth", "direction": "output"},
            need_id="N01",
            index=0,
        )
    except WorkerContractViolation as exc:
        assert exc.code == "unknown_need_semantic_requirement"
    else:
        raise AssertionError("unknown semantic requirement was not rejected")


def test_need_completion_requires_declared_business_output() -> None:
    from agent.collaboration.completion import evaluate_need_completion

    intent = {
        "needs": [{
            "need_id": "N02",
            "kind": "business",
            "description": "形成调仓方案",
            "required": True,
            "requirements": [{
                "requirement_id": "N02-R01",
                "semantic_key": "rebalance_proposal",
                "direction": "output",
                "slot_id": "reviewed_proposal",
                "required": True,
            }],
        }]
    }
    false_positive = evaluate_need_completion(intent, [{
        "semantic_satisfied": True,
        "produced_information_slots": ["current_portfolio_state"],
        "failure_kind": "none",
        "completion": {"business_status": "sufficient"},
    }])
    completed = evaluate_need_completion(intent, [{
        "semantic_satisfied": True,
        "produced_information_slots": ["reviewed_proposal"],
        "failure_kind": "none",
        "completion": {"business_status": "sufficient"},
    }])
    assert false_positive["needs"][0]["status"] == "not_completed"
    assert false_positive["goal_status"] == "not_completed"
    assert completed["needs"][0]["status"] == "completed"


def test_structured_fundamentals_need_cannot_be_satisfied_by_unrelated_news_slot() -> None:
    from agent.capabilities import CapabilityTask, SlotBinder

    compiler = NeedRequirementCompiler(CapabilityRegistry(), CapabilityWorkerDirectory())
    fundamentals = compiler.normalize_requirement(
        {"semantic_key": "entity_fundamentals", "direction": "input", "required": True},
        need_id="N01", index=0,
    )
    analysis = compiler.normalize_requirement(
        {"semantic_key": "entity_analysis", "direction": "output", "required": True},
        need_id="N01", index=1,
    )
    raw_tasks = compiler.expand_compact_tasks(
        intent_contract={"needs": [{"need_id": "N01", "required": True, "requirements": [fundamentals, analysis]}]},
        worker_calls=[{
            "call_id": "WC01", "worker_id": "W09", "covers_need_ids": ["N01"],
            "objective": "基于结构化财务事实形成分析",
            "desired_output_slots": ["entity_analysis"],
        }],
        task_requirements=[{
            "call_id": "WC01", "requirement_ids": ["N01-R01"], "additional_required_slots": []
        }],
        initial_slots={"entity_external_evidence"},
        request_mode="analysis",
    )
    task = CapabilityTask.from_dict({**raw_tasks[0], "task_id": "T01"}, task_id="T01")
    try:
        SlotBinder().bind([task], initial_information_slots={"entity_external_evidence"})
    except WorkerContractViolation as exc:
        assert exc.code == "capability_required_input_has_no_producer"
        assert exc.detail == "entity_fundamentals"
    else:
        raise AssertionError("news/evidence incorrectly substituted for entity_fundamentals")
