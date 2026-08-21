from __future__ import annotations

from agent.capabilities import CapabilityContract, CapabilityContractValidator
from agent.collaboration.models import GraphAgentTask
from agent.context.context_types import ContextBundle


def _task():
    return GraphAgentTask(task_id="T",run_id="r",session_id="s",worker_id="W02",assigned_agent="PORTFOLIO_ANALYST",objective="查询",user_id="u",boundary_id="system_internal_fact_provider",contracts=[{"contract_id":"C","required_data":[],"required_parameters":[],"promised_data":[{"name":"prediction"}],"acceptance_rule_ids":["schema_valid","business_empty_explicit"],"mutation_allowed":False,"allowed_terminal_states":["completed","business_empty"]}],expected_data_names=["prediction"])


def test_capability_contract_uses_business_data_names_not_transport_bindings() -> None:
    c=CapabilityContract.from_dict(_task().contracts[0])
    assert c.output_data_names() == ["prediction"]
    assert not hasattr(c,"required_inputs") and not hasattr(c,"promised_outputs")


def test_empty_materialized_data_satisfies_query_completion_contract() -> None:
    validator=CapabilityContractValidator()
    report=validator.validate(contracts=[CapabilityContract.from_dict(x) for x in _task().contracts],produced_data_names={"prediction"},materialized_data={"prediction":{}},result_status="completed",result_payload={"business_empty":True})[0]
    assert report.status == "business_empty"
    assert report.missing_outputs == []


def test_contextbundle_is_the_run_business_data_store() -> None:
    bundle=ContextBundle(user_id="u",conversation_id="s",run_id="r")
    bundle.put_business_data(entity_ref=None,name="prediction",value={})
    assert bundle.business_data_context()["global_data"] == {"prediction":{}}


def test_mutation_permission_is_separate_from_proposal_generation() -> None:
    from agent.collaboration.worker_directory import CapabilityWorkerDirectory
    d=CapabilityWorkerDirectory()
    assert d.get("W05").can_mutate is False
    assert d.get("W08").can_mutate is True
