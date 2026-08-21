from __future__ import annotations

from agent.capabilities import (
    BusinessParameterResolver,
    CapabilityContract,
    CapabilityPlanValidator,
    CapabilityRegistry,
)
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def _contract_dict() -> dict:
    return {
        "contract_id": "T04-C01",
        "description": "评估目标标的加入组合后的影响",
        "required_data": [
            {"name": "portfolio", "semantic_role": "current_portfolio", "required": True},
            {"name": "analysis", "semantic_role": "impact_source", "required": True},
        ],
        "required_parameters": [{
            "parameter_id": "target_asset_allocation",
            "semantic_role": "target_allocation",
            "source_policy": "user",
            "satisfaction_rule": "one_of",
            "satisfy_by": ["target_weight", "target_amount"],
            "description": "目标配置比例或投入金额",
            "expected_format": "percentage or cash amount",
            "required": True,
        }],
        "promised_data": [{"name": "risk"}],
        "acceptance_rule_ids": ["schema_valid"],
        "criticality": "required",
        "mutation_allowed": False,
        "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
    }


def _task(*, business_parameters: dict | None = None) -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T04", run_id="run-v2316", session_id="session-v2316",
        worker_id="W04", assigned_agent="RISK_ANALYST",
        objective="评估目标标的加入当前组合后的风险影响", user_id="cht",
        boundary_id="portfolio_risk_assessment", contracts=[_contract_dict()],
        business_parameters=dict(business_parameters or {}), expected_data_names=["risk"],
    )


def test_capability_contract_roundtrip_keeps_data_and_parameter_semantics() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    assert contract.required_data[1].semantic_role == "impact_source"
    assert contract.required_data[1].name == "analysis"
    assert contract.required_parameters[0].parameter_id == "target_asset_allocation"
    assert contract.required_parameters[0].satisfy_by == ["target_weight", "target_amount"]
    assert contract.to_dict()["required_parameters"][0]["semantic_role"] == "target_allocation"


def test_plan_validator_accepts_w04_working_memory_data_contract() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    payload = {
        "goal_contract": {"desired_outputs": ["risk"], "required_context_names": []},
        "tasks": [{
            "task_id": "T04", "worker_id": "W04", "boundary_id": "portfolio_risk_assessment",
            "objective": "评估目标标的加入组合后的风险影响", "contracts": [_contract_dict()],
            "business_parameters": {},
        }],
    }
    tasks = validator.validate(payload)
    assert tasks[0].input_data_names() == ["portfolio", "analysis"]
    assert tasks[0].contracts[0].required_parameters[0].parameter_id == "target_asset_allocation"


def test_parameter_resolver_only_blocks_missing_user_parameter() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    resolution = BusinessParameterResolver().resolve(
        contracts=[contract], business_parameters={}, available_parameters={}
    )
    assert resolution.failure_kind == "user_input_required"
    assert [gap.parameter_id for gap in resolution.gaps] == ["target_asset_allocation"]
    # Runtime does not turn absent business data into a pre-execution input gate.
    assert not hasattr(resolution, "system_gaps")


def test_parameter_resolver_accepts_either_target_weight_or_amount() -> None:
    contract = CapabilityContract.from_dict(_contract_dict())
    by_weight = BusinessParameterResolver().resolve(
        contracts=[contract], business_parameters={"target_weight": 0.05}
    )
    by_amount = BusinessParameterResolver().resolve(
        contracts=[contract], business_parameters={"target_amount": 20000}
    )
    assert by_weight.satisfied is True
    assert by_amount.satisfied is True


def test_specialist_runtime_blocks_user_parameter_before_worker_execution() -> None:
    runtime = SpecialistRuntime.__new__(SpecialistRuntime)
    runtime.parameter_resolver = BusinessParameterResolver()
    result = runtime._parameter_gate(_task(), {"available_parameters": {}}, "zh")
    assert result is not None
    assert result.status == ResultStatus.NEED_CONTEXT
    assert result.error["error_id"] == "user_input_required"
    assert [item.key for item in result.missing_items] == ["target_asset_allocation"]
    assert result.metadata["input_gate_owner"] == "runtime"


def test_specialist_runtime_does_not_preblock_missing_business_data() -> None:
    runtime = SpecialistRuntime.__new__(SpecialistRuntime)
    runtime.parameter_resolver = BusinessParameterResolver()
    # Business data is judged by W04/W05/W09 from ContextBundle, not by a Runtime resolver.
    assert runtime._parameter_gate(
        _task(business_parameters={"target_weight": 0.05}), {"available_parameters": {}}, "zh"
    ) is None


def test_plan_validator_rejects_mutation_contract_for_non_mutating_w04() -> None:
    validator = CapabilityPlanValidator(CapabilityRegistry(), CapabilityWorkerDirectory())
    contract = _contract_dict(); contract["mutation_allowed"] = True
    payload = {
        "goal_contract": {"desired_outputs": ["risk"], "required_context_names": []},
        "tasks": [{"task_id": "T04", "worker_id": "W04", "boundary_id": "portfolio_risk_assessment",
                   "objective": "评估组合风险", "contracts": [contract], "business_parameters": {}}],
    }
    try:
        validator.validate(payload)
    except Exception as exc:
        assert "capability_mutation_not_allowed_for_worker" in str(exc)
    else:
        raise AssertionError("W04 mutation permission violation was not rejected")
