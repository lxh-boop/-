from __future__ import annotations

from agent.capabilities import CapabilityRegistry, NeedRequirementCompiler
from agent.collaboration.completion import evaluate_need_completion
from agent.collaboration.worker_directory import CapabilityWorkerDirectory


def _request_need_contract(requirements):
    compiler=NeedRequirementCompiler(CapabilityRegistry(),CapabilityWorkerDirectory())
    normalized=compiler.normalize_need_requirements(need_id="N01",raw_requirements=requirements,strict=True)
    return {"requirement_contract_version":"need-requirement.v2","needs":[{"need_id":"N01","required":True,"requirements":normalized}]}


def test_v2_semantics_map_to_simple_working_memory_data_names() -> None:
    request_need_contract=_request_need_contract([
        {"semantic_key":"external_evidence","direction":"output","required":True},
        {"semantic_key":"entity_model_signals","direction":"output","required":True},
        {"semantic_key":"entity_analysis","direction":"output","required":True},
    ])
    names=[r["data_name"] for r in request_need_contract["needs"][0]["requirements"]]
    assert names == ["evidence","prediction","analysis"]


def test_analysis_input_semantics_do_not_become_point_to_point_data_contracts() -> None:
    compiler=NeedRequirementCompiler(CapabilityRegistry(),CapabilityWorkerDirectory())
    request_need_contract=_request_need_contract([
        {"semantic_key":"external_evidence","direction":"input","required":True},
        {"semantic_key":"entity_model_signals","direction":"input","required":True},
        {"semantic_key":"entity_analysis","direction":"output","required":True},
    ])
    calls=[{"call_id":"WC01","worker_id":"W09","objective":"分析股票","covers_need_ids":["N01"],"desired_output_data_names":["analysis"]}]
    assignments=compiler.compile_task_requirements(request_need_contract=request_need_contract,worker_calls=calls)
    tasks=compiler.expand_compact_tasks(request_need_contract=request_need_contract,worker_calls=calls,task_requirements=assignments)
    assert tasks[0]["contracts"][0]["required_data"] == []
    assert tasks[0]["contracts"][0]["promised_data"] == [{"name":"analysis","required_paths":[]}]


def test_target_allocation_remains_explicit_user_parameter() -> None:
    compiler=NeedRequirementCompiler(CapabilityRegistry(),CapabilityWorkerDirectory())
    request_need_contract=_request_need_contract([
        {"semantic_key":"target_allocation","direction":"parameter","required":True},
        {"semantic_key":"portfolio_risk","direction":"output","required":True},
    ])
    calls=[{"call_id":"WC01","worker_id":"W04","objective":"评估风险","covers_need_ids":["N01"],"desired_output_data_names":["risk"]}]
    assignments=compiler.compile_task_requirements(request_need_contract=request_need_contract,worker_calls=calls)
    tasks=compiler.expand_compact_tasks(request_need_contract=request_need_contract,worker_calls=calls,task_requirements=assignments)
    params=tasks[0]["contracts"][0]["required_parameters"]
    assert params[0]["parameter_id"] == "target_asset_allocation"
    assert "target_weight" in params[0]["satisfy_by"]


def test_need_completion_uses_materialized_data_names() -> None:
    request_need_contract=_request_need_contract([{"semantic_key":"entity_analysis","direction":"output","required":True}])
    completed=evaluate_need_completion(request_need_contract,[{"semantic_satisfied":True,"produced_data_names":["analysis"]}])
    missing=evaluate_need_completion(request_need_contract,[{"semantic_satisfied":False,"produced_data_names":[]}])
    assert completed["goal_status"] == "completed"
    assert missing["goal_status"] == "not_completed"
    assert missing["needs"][0]["missing_output_data_names"] == ["analysis"]


def test_empty_query_result_name_still_counts_as_completed() -> None:
    request_need_contract=_request_need_contract([{"semantic_key":"external_evidence","direction":"output","required":True}])
    report=evaluate_need_completion(request_need_contract,[{"semantic_satisfied":True,"produced_data_names":["evidence"],"completion":{"business_status":"empty"}}])
    assert report["goal_status"] == "completed"
