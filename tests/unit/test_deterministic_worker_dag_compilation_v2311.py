from __future__ import annotations

from agent.capabilities import CapabilityContract
from agent.collaboration.planner import CoordinatorPlanner
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


class _TwoStageLLM:
    """A V23.0.11 MainAgent stub: intent + Worker assignment only."""

    def __init__(self) -> None:
        self.stages: list[str] = []

    def generate_json(self, **kwargs):
        stage = kwargs["stage"]
        self.stages.append(stage)
        if stage == "upfront_user_intent_planning":
            payload = {
                "requirement_contract_version": "need-requirement.v1",
                "intent_summary": "读取组合状态并由系统生成待审批调仓建议。",
                "needs": [
                    {
                        "description": "获取当前组合和用户约束",
                        "required": True,
                        "requirements": [
                            {"semantic_key": "portfolio_state", "direction": "output", "required": True},
                            {"semantic_key": "portfolio_positions", "direction": "output", "required": True},
                            {"semantic_key": "user_constraints", "direction": "output", "required": True},
                        ],
                    },
                    {
                        "description": "基于当前组合和约束形成系统推荐的调仓方案",
                        "required": True,
                        "requirements": [
                            {"semantic_key": "portfolio_state", "direction": "input", "required": True},
                            {"semantic_key": "portfolio_positions", "direction": "input", "required": True},
                            {"semantic_key": "user_constraints", "direction": "input", "required": True},
                            {"semantic_key": "rebalance_proposal", "direction": "output", "required": True},
                            {"semantic_key": "rebalance_instructions", "direction": "output", "required": True},
                        ],
                    },
                ],
                "constraints": [],
                "scope_note": "当前完整组合",
                "effect_limit": "proposal",
            }
        elif stage == "upfront_worker_call_selection":
            payload = {
                "worker_calls": [
                    {
                        "call_id": "WC01",
                        "worker_id": "W02",
                        "objective": "读取当前组合和用户约束",
                        "covers_need_ids": ["N01"],
                        "desired_output_slots": [
                            "current_portfolio_state",
                            "portfolio_positions",
                            "user_constraints",
                        ],
                    },
                    {
                        "call_id": "WC02",
                        "worker_id": "W05",
                        "objective": "形成待审批调仓方案",
                        "covers_need_ids": ["N02"],
                        "desired_output_slots": ["reviewed_proposal", "proposal.rebalance"],
                    },
                    {
                        "call_id": "WC03",
                        "worker_id": "W06",
                        "objective": "生成最终用户回答",
                        "covers_need_ids": ["N_FINAL"],
                        "desired_output_slots": ["user_facing_report"],
                    },
                ],
                "selection_reason": "事实读取->方案->报告",
            }
        else:
            raise AssertionError(f"unexpected third MainAgent LLM stage: {stage}")
        kwargs["validator"](payload)
        return payload


def test_new_run_uses_only_two_mainagent_llm_planning_stages() -> None:
    llm = _TwoStageLLM()
    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=llm,
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, metadata = planner.plan(
        query="你认为我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s-v2311",
        run_id="r-v2311",
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
    assert tasks[0].dependency_task_ids == []
    assert tasks[1].dependency_task_ids == ["T01"]
    assert tasks[2].dependency_task_ids == ["T02"]
    assert metadata["planner"] == "need_worker_assignment_runtime_compiler"
    assert metadata["planning_mode"] == (
        "intent_need_then_worker_assignment_then_runtime_dag_compile_then_private_tool_dag"
    )
    assert metadata["capability_plan"]["contract_expansion_mode"] == (
        "deterministic_need_worker_dag_compiler"
    )


def test_need_inputs_are_attached_to_need_output_owner_not_data_provider() -> None:
    llm = _TwoStageLLM()
    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=llm,
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, _ = planner.plan(
        query="你认为我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s-v2311-owner",
        run_id="r-v2311-owner",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )

    provider_contract = CapabilityContract.from_dict(tasks[0].contracts[0])
    proposal_contract = CapabilityContract.from_dict(tasks[1].contracts[0])
    report_contract = CapabilityContract.from_dict(tasks[2].contracts[0])

    assert provider_contract.input_slots(required_only=True) == ["user_identity"]
    assert set(proposal_contract.input_slots(required_only=True)) == {
        "current_portfolio_state",
        "portfolio_positions",
        "user_constraints",
    }
    # Presentation is compiled as a terminal sink. It consumes the terminal
    # professional business outputs, not every raw upstream fact.
    assert set(report_contract.input_slots(required_only=True)) == {
        "reviewed_proposal",
        "proposal.rebalance",
    }


def test_worker_private_planning_boundary_is_preserved_in_compiled_metadata() -> None:
    llm = _TwoStageLLM()
    planner = CoordinatorPlanner(
        CapabilityWorkerDirectory(),
        llm_service=llm,
        worker_tool_directory=_ScopeToolDirectory(),
    )
    tasks, _ = planner.plan(
        query="你认为我的持仓应该怎么调整？",
        request_mode="proposal",
        session_id="s-v2311-private",
        run_id="r-v2311-private",
        user_id="u",
        focus_refs=[],
        context_refs=[],
        memory_summary="",
    )

    for task in tasks:
        assert task.metadata["structured_capability_contract"] is True
        assert task.metadata["upfront_worker_dag"] is True
        # Runtime compiles Worker-to-Worker dependencies, but the Worker still
        # owns its private Tool planning/execution later in SpecialistRuntime.
        assert task.execution_mode in {"hybrid", "pure_llm", "deterministic"}
