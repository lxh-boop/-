from __future__ import annotations

from types import SimpleNamespace

from agent.capabilities import (
    CapabilityContract,
    CapabilityPlanValidator,
    CapabilityRegistry,
    RequirementResolver,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def _contract_dict() -> dict:
    return {
        "contract_id": "T04-C01",
        "description": "评估目标标的加入组合后的影响",
        "required_inputs": [
            {
                "slot_id": "current_portfolio_state",
                "semantic_role": "current_portfolio",
                "source_policy": "system",
                "satisfaction_rule": "exists",
                "required": True,
            },
            {
                "slot_id": "entity_analysis",
                "semantic_role": "impact_source",
                "source_policy": "system",
                "satisfaction_rule": "non_empty",
                "required": True,
            },
        ],
        "required_parameters": [
            {
                "parameter_id": "target_asset_allocation",
                "semantic_role": "target_allocation",
                "source_policy": "user",
                "satisfaction_rule": "one_of",
                "satisfy_by": ["target_weight", "target_amount"],
                "description": "目标配置比例或投入金额",
                "expected_format": "percentage or cash amount",
                "required": True,
            }
        ],
        "promised_outputs": [
            {"slot_id": "portfolio_risk_result", "provenance_required": True}
        ],
        "acceptance_rule_ids": ["schema_valid"],
        "criticality": "required",
        "effect_limit": "read",
        "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
    }


def _task(*, business_parameters: dict | None = None) -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T04",
        run_id="run-v2309",
        session_id="session-v2309",
        worker_id="W04",
        assigned_agent="RISK_ANALYST",
        objective="评估目标标的加入当前组合后的风险影响",
        user_id="cht",
        boundary_id="portfolio_risk_assessment",
        contracts=[_contract_dict()],
        business_parameters=dict(business_parameters or {}),
        expected_output_slots=["portfolio_risk_result"],
    )


def test_capability_contract_roundtrip_keeps_semantic_requirements() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    assert contract.required_inputs[1].semantic_role == "impact_source"
    assert contract.required_inputs[1].source_policy == "system"
    assert contract.required_inputs[1].satisfaction_rule == "non_empty"
    assert contract.required_parameters[0].parameter_id == "target_asset_allocation"
    assert contract.required_parameters[0].source_policy == "user"
    assert contract.required_parameters[0].satisfy_by == ["target_weight", "target_amount"]
    assert contract.to_dict()["required_parameters"][0]["semantic_role"] == "target_allocation"


def test_plan_validator_allows_w04_to_consume_verified_entity_analysis() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    payload = {
        "goal_contract": {
            "desired_outputs": ["portfolio_risk_result"],
            "required_information_slots": [],
            "effect_limit": "read",
        },
        "tasks": [{
            "task_id": "T04",
            "worker_id": "W04",
            "boundary_id": "portfolio_risk_assessment",
            "objective": "评估目标标的加入组合后的风险影响",
            "contracts": [_contract_dict()],
            "business_parameters": {},
            "effect_limit": "read",
        }],
    }
    tasks = validator.validate(
        payload,
        request_mode="analysis",
        initial_information_slots={"current_portfolio_state", "entity_analysis"},
    )
    assert tasks[0].input_slots() == ["current_portfolio_state", "entity_analysis"]
    assert tasks[0].contracts[0].required_parameters[0].parameter_id == "target_asset_allocation"


def test_requirement_resolver_prefers_system_gap_over_user_gap() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    resolution = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs={"current_portfolio_state": {"total_assets": 100000}},
        business_parameters={},
    )
    assert resolution.failure_kind == "worker_input_slot_unresolved"
    assert [gap.requirement_id for gap in resolution.system_gaps] == ["entity_analysis"]
    assert [gap.requirement_id for gap in resolution.user_gaps] == ["target_asset_allocation"]


def test_requirement_resolver_accepts_either_target_weight_or_amount() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    base_inputs = {
        "current_portfolio_state": {"total_assets": 100000},
        "entity_analysis": {"conclusion": "verified"},
    }
    by_weight = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs=base_inputs,
        business_parameters={"target_weight": 0.05},
    )
    by_amount = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs=base_inputs,
        business_parameters={"target_amount": 20000},
    )
    assert by_weight.satisfied is True
    assert by_amount.satisfied is True


def test_requirement_resolver_is_business_agnostic_for_news_impact() -> None:
    contract = CapabilityContract.from_dict({
        "contract_id": "NEWS-C01",
        "required_inputs": [
            {
                "slot_id": "portfolio_positions",
                "semantic_role": "current_portfolio",
                "source_policy": "system",
                "required": True,
            },
            {
                "slot_id": "impact_facts",
                "semantic_role": "impact_source",
                "source_policy": "system",
                "satisfaction_rule": "non_empty",
                "required": True,
            },
        ],
        "promised_outputs": [{"slot_id": "portfolio_risk_result"}],
    })
    missing = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs={"portfolio_positions": [{"security_ref": "600519"}]},
        business_parameters={},
    )
    satisfied = RequirementResolver().resolve(
        contracts=[contract],
        resolved_inputs={
            "portfolio_positions": [{"security_ref": "600519"}],
            "impact_facts": {"direction": "negative", "confidence": 0.8},
        },
        business_parameters={},
    )
    assert missing.failure_kind == "worker_input_slot_unresolved"
    assert missing.system_gaps[0].requirement_id == "impact_facts"
    assert satisfied.satisfied is True


class _Projection:
    def __init__(self, resolved_inputs: dict):
        self.resolved_inputs = resolved_inputs

    def project(self, task, execution_context=None):
        return dict(self.resolved_inputs), []


def _runtime_for_gate(resolved_inputs: dict) -> SpecialistRuntime:
    runtime = SpecialistRuntime.__new__(SpecialistRuntime)
    runtime.input_projection = _Projection(resolved_inputs)
    runtime.requirement_resolver = RequirementResolver()
    return runtime


def test_specialist_runtime_blocks_user_parameter_before_worker_execution(tmp_path) -> None:
    runtime = _runtime_for_gate({
        "current_portfolio_state": {"total_assets": 100000},
        "entity_analysis": {"conclusion": "verified"},
    })
    result = runtime.run(
        _task(),
        current_user_request="把它加进去怎么样",
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
        execution_context={"available_parameters": {}},
    )
    assert result.status == ResultStatus.NEED_CONTEXT
    assert result.error["error_id"] == "user_input_required"
    assert result.error["retryable"] is False
    assert [item.key for item in result.missing_items] == ["target_asset_allocation"]
    assert result.metadata["input_gate_owner"] == "runtime_requirement_resolver"
    assert result.metadata["replan_recommended"] is False


def test_specialist_runtime_blocks_internal_slot_before_user_question(tmp_path) -> None:
    runtime = _runtime_for_gate({"current_portfolio_state": {"total_assets": 100000}})
    result = runtime.run(
        _task(),
        current_user_request="把它加进去怎么样",
        output_dir=tmp_path,
        db_path=None,
        default_top_k=10,
        language="zh",
        execution_context={"available_parameters": {}},
    )
    assert result.status == ResultStatus.NEED_CONTEXT
    assert result.error["error_id"] == "worker_input_slot_unresolved"
    assert result.error["retryable"] is True
    assert [item.key for item in result.missing_items] == ["entity_analysis"]
    assert result.metadata["replan_recommended"] is True


def test_plan_validator_rejects_llm_invented_user_parameter_outside_worker_schema() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    contract = _contract_dict()
    contract["required_parameters"] = [{
        "parameter_id": "favorite_color",
        "semantic_role": "arbitrary_preference",
        "source_policy": "user",
        "satisfaction_rule": "one_of",
        "satisfy_by": ["favorite_color"],
        "required": True,
    }]
    payload = {
        "goal_contract": {
            "desired_outputs": ["portfolio_risk_result"],
            "required_information_slots": [],
            "effect_limit": "read",
        },
        "tasks": [{
            "task_id": "T04",
            "worker_id": "W04",
            "boundary_id": "portfolio_risk_assessment",
            "objective": "评估组合风险",
            "contracts": [contract],
            "business_parameters": {},
            "effect_limit": "read",
        }],
    }
    try:
        validator.validate(
            payload,
            request_mode="analysis",
            initial_information_slots={"current_portfolio_state", "entity_analysis"},
        )
    except Exception as exc:
        assert "capability_business_parameter_outside_worker_scope" in str(exc)
    else:
        raise AssertionError("LLM-invented parameter requirement must be rejected by static Worker capability schema")
