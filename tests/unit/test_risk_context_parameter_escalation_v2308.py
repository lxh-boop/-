from __future__ import annotations

from agent.capabilities import BusinessParameterResolver, CapabilityContract
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime


def _contract():
    return CapabilityContract.from_dict({"contract_id":"C","required_data":[],"required_parameters":[{"parameter_id":"target_asset_allocation","source_policy":"user","satisfaction_rule":"one_of","satisfy_by":["target_weight","target_amount"],"required":True}],"promised_data":[{"name":"risk"}],"mutation_allowed":False})


def _task(params=None):
    return GraphAgentTask(task_id="T",run_id="r",session_id="s",worker_id="W04",assigned_agent="RISK_ANALYST",objective="风险情景",user_id="u",boundary_id="portfolio_risk_assessment",contracts=[_contract().to_dict()],business_parameters=dict(params or {}),expected_data_names=["risk"])


def test_runtime_only_routes_missing_explicit_user_parameter_to_user_input() -> None:
    runtime=SpecialistRuntime.__new__(SpecialistRuntime); runtime.parameter_resolver=BusinessParameterResolver()
    result=runtime._parameter_gate(_task(),{"available_parameters":{}},"zh")
    assert result.status == ResultStatus.NEED_CONTEXT
    assert result.error["error_id"] == "user_input_required"


def test_target_weight_satisfies_generic_business_parameter_contract() -> None:
    resolution=BusinessParameterResolver().resolve(contracts=[_contract()],business_parameters={"target_weight":0.1})
    assert resolution.satisfied is True


def test_business_data_is_not_prevalidated_by_runtime_parameter_gate() -> None:
    runtime=SpecialistRuntime.__new__(SpecialistRuntime); runtime.parameter_resolver=BusinessParameterResolver()
    assert runtime._parameter_gate(_task({"target_amount":10000}),{"available_parameters":{}},"zh") is None
