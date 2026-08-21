from __future__ import annotations

import json

from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.collaboration.workers.evidence import _canonical_payload, _canonical_record
from agent.context.token_budget import estimate_tokens
from agent.graph.contracts import GraphNodeKind, GraphRef


def _ref():
    return GraphRef(graph_id="financial_graph",node_id="cn:security:sse:600519",node_kind=GraphNodeKind.OBJECT,role="focus",source="test",confidence=1.0,locked=True)


def test_canonical_evidence_keeps_one_bounded_body_representation() -> None:
    row={"canonical_id":"e1","source_id":"s1","source":"unit","title":"公告","publish_time":"2026-08-10","summary":"摘要"*100,"text":"正文"*2000,"content":"重复"*2000,"retrieved_by":["news_and_announcements"]}
    projected=_canonical_record(row)
    assert projected["canonical_id"] == "e1"
    assert projected["text_source_field"] == "summary"
    assert "content" not in projected and "summary" not in projected


def test_canonical_evidence_payload_is_working_memory_ready_and_bounded() -> None:
    long={"canonical_id":"e1","source_id":"s1","source":"unit","title":"证据","publish_time":"2026-08-10","text":"正文"*3000,"retrieved_by":["rag_evidence"]}
    payload=_canonical_payload(selected_refs=[_ref()],entity_catalog=[{"node_id":_ref().node_id}],collection_goal="分析600519",results=[{"focus_ref":_ref().to_dict(),"success":True,"records":[long],"source_names":["rag_evidence"],"warnings":[],"errors":[]}],record_count=1,source_count=1,deduplication={},coverage={"coverage_satisfied":True},business_empty=False)
    record=payload["results"][0]["records"][0]
    assert record["text_truncated"] is True and len(record["text"]) <= 1000
    assert estimate_tokens(payload) < 8000


def test_w09_receives_canonical_evidence_via_contextbundle_view_without_producer_identity() -> None:
    evidence={"record_count":1,"results":[{"records":[{"canonical_id":"e1","title":"测试证据","text":"业务事实"}]}]}
    task=GraphAgentTask(task_id="T02",run_id="r",session_id="s",worker_id="W09",assigned_agent="ENTITY_ANALYST",objective="分析600519",user_id="u",boundary_id="entity_analysis",contracts=[{"contract_id":"C","required_data":[],"required_parameters":[],"promised_data":[{"name":"analysis"},{"name":"analysis_uncertainty"}],"acceptance_rule_ids":[],"mutation_allowed":False,"allowed_terminal_states":["completed"]}],expected_data_names=["analysis","analysis_uncertainty"],focus_refs=[_ref()])
    class LLM:
        def generate_text(self, **kwargs):
            text="\n".join(str(m.get("content") or "") for m in kwargs["messages"])
            assert "e1" in text and "业务事实" in text
            assert "W01" not in text
            return json.dumps({"context_sufficient":True,"missing_information":[],"facts":[{"claim_id":"F1","statement":"存在业务事实"}],"analysis":[],"uncertainties":[],"conclusion":"完成"},ensure_ascii=False)
    context={"schema_version":"context_bundle_business_data.v1","run_id":"r","entities":[{"entity_ref":_ref().to_dict(),"data":{"evidence":evidence}}],"global_data":{},"available_names":["evidence"]}
    result=run_entity_analysis(LLM(),task,working_memory_context=context,language="zh")
    assert result.status == ResultStatus.COMPLETED
    assert result.data["business_data"]["analysis"]["facts"]
