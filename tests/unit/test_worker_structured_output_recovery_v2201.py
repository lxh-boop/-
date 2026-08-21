from __future__ import annotations

import json

from agent.collaboration.completion import flow_decision
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.specialist_runtime import SpecialistRuntime
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.context.context_types import ContextBundle
from agent.graph.contracts import GraphNodeKind, GraphRef


def _ref():
    return GraphRef(graph_id="financial_graph",node_id="cn:security:sse:600519",node_kind=GraphNodeKind.OBJECT,role="focus",source="test",confidence=1.0,locked=True)


def _task():
    return GraphAgentTask(task_id="T02",run_id="run",session_id="s",worker_id="W09",assigned_agent="ENTITY_ANALYST",objective="分析贵州茅台",user_id="u",boundary_id="entity_analysis",contracts=[{"contract_id":"C","required_data":[],"required_parameters":[],"promised_data":[{"name":"analysis"},{"name":"analysis_uncertainty"}],"acceptance_rule_ids":[],"mutation_allowed":False,"allowed_terminal_states":["completed","business_insufficient"]}],expected_data_names=["analysis","analysis_uncertainty"],focus_refs=[_ref()])


def _context():
    return {"schema_version":"context_bundle_business_data.v1","run_id":"run","entities":[{"entity_ref":_ref().to_dict(),"data":{"evidence":{"records":[{"title":"测试证据","text":"SECRET_EVIDENCE_MARKER 贵州茅台经营信息"}]}}}],"global_data":{},"available_names":["evidence"]}


def _valid():
    return {"context_sufficient":True,"missing_information":[],"facts":[{"claim_id":"F01","statement":"存在经营信息"}],"analysis":[{"claim_id":"A01","statement":"可形成分析"}],"uncertainties":[],"conclusion":"完成"}


def test_w09_truncated_json_uses_structural_only_local_repair() -> None:
    class LLM:
        def __init__(self): self.calls=[]
        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls)==1: return '{"context_sufficient":true,"facts":[{"claim_id":"F01","statement":"截断'
            return json.dumps(_valid(),ensure_ascii=False)
    llm=LLM(); result=run_entity_analysis(llm,_task(),working_memory_context=_context(),language="zh")
    assert result.status == ResultStatus.COMPLETED and len(llm.calls)==2
    primary="\n".join(str(x.get("content") or "") for x in llm.calls[0]["messages"])
    repair="\n".join(str(x.get("content") or "") for x in llm.calls[1]["messages"])
    assert primary.count("SECRET_EVIDENCE_MARKER") == 1
    assert "SECRET_EVIDENCE_MARKER" not in repair
    assert result.data["business_data"]["analysis"]["facts"]


def test_w09_local_recovery_exhaustion_is_non_retryable_and_writes_no_working_memory() -> None:
    class LLM:
        def generate_text(self, **kwargs): return '{"context_sufficient":'
    task=_task(); result=run_entity_analysis(LLM(),task,working_memory_context=_context(),language="zh")
    assert result.status == ResultStatus.FAILED and result.error["retryable"] is False
    runtime=SpecialistRuntime.__new__(SpecialistRuntime); runtime.context_bundle=ContextBundle(user_id="u",conversation_id="s",run_id="run")
    assert runtime._publish_business_data(task,result) == []
    assert runtime.context_bundle.business_data == []


def test_failed_result_never_publishes_even_if_payload_contains_business_data() -> None:
    task=_task(); runtime=SpecialistRuntime.__new__(SpecialistRuntime); runtime.context_bundle=ContextBundle(user_id="u",conversation_id="s",run_id="run")
    failed=GraphWorkerResult(task_id=task.task_id,agent_id=task.assigned_agent,status=ResultStatus.FAILED,data={"business_data":{"analysis":{"facts":[]}},"produced_data_names":["analysis"]})
    assert runtime._publish_business_data(task,failed) == []
    assert runtime.context_bundle.business_data == []


def test_blocked_downstream_replan_follows_retryability() -> None:
    completion={"expected_task_completed":False,"failure_kind":"upstream_worker_failed"}
    assert flow_decision(ResultStatus.BLOCKED,completion,retryable=False).replan_recommended is False
    assert flow_decision(ResultStatus.BLOCKED,completion,retryable=True).replan_recommended is True
