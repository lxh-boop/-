from __future__ import annotations

import json
from pathlib import Path

from agent.collaboration.completion import build_completion_report, flow_decision
from agent.collaboration.models import GraphAgentTask, GraphWorkerResult, ResultStatus
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.runtime_state import RunSlotStore


def _ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind=GraphNodeKind.OBJECT,
        role="focus",
        source="test",
        confidence=1.0,
        locked=True,
    )


def _analysis_task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T02",
        run_id="run",
        session_id="session",
        worker_id="W09",
        assigned_agent="ENTITY_ANALYST",
        objective="分析贵州茅台",
        user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "T02-C01",
            "required_inputs": [
                {"slot_id": "authoritative_entity_refs", "required": True},
                {"slot_id": "entity_external_evidence", "required": True},
                {"slot_id": "evidence_source_records", "required": True},
            ],
            "promised_outputs": [
                {"slot_id": "entity_analysis"},
                {"slot_id": "entity_analysis_uncertainty"},
            ],
            "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
        }],
        resolved_input_bindings=[
            {
                "source_type": "runtime_context",
                "output_slot_id": "authoritative_entity_refs",
                "input_slot_id": "authoritative_entity_refs",
            },
            {
                "source_type": "upstream_task",
                "output_slot_id": "entity_external_evidence",
                "input_slot_id": "entity_external_evidence",
                "producer_task_id": "T01",
                "producer_contract_id": "T01-C01",
            },
            {
                "source_type": "upstream_task",
                "output_slot_id": "evidence_source_records",
                "input_slot_id": "evidence_source_records",
                "producer_task_id": "T01",
                "producer_contract_id": "T01-C01",
            },
        ],
        expected_output_slots=["entity_analysis", "entity_analysis_uncertainty"],
        focus_refs=[_ref()],
        metadata={
            "authoritative_entity_catalog": [{"node_id": "cn:security:sse:600519", "display_name": "贵州茅台"}]
        },
    )


def _evidence_payload() -> dict:
    return {
        "entity_refs": [_ref().to_dict()],
        "entity_catalog": [{"node_id": "cn:security:sse:600519", "display_name": "贵州茅台"}],
        "results": [{
            "focus_ref": _ref().to_dict(),
            "source_names": ["unit-test"],
            "records": [{
                "source_id": "s1",
                "source": "unit-test",
                "title": "测试证据",
                "text": "SECRET_EVIDENCE_MARKER 贵州茅台经营信息",
                "date": "2026-08-07",
            }],
            "sources": [],
            "warnings": [],
            "errors": [],
        }],
        "record_count": 1,
        "source_count": 1,
        "coverage": {"coverage_satisfied": True},
        "deduplication": {},
        "business_empty": False,
    }


def _resolved_inputs() -> dict:
    evidence = _evidence_payload()
    return {
        "authoritative_entity_refs": [_ref().to_dict()],
        "entity_external_evidence": evidence,
        "evidence_source_records": evidence,
    }


def _valid_analysis() -> dict:
    return {
        "entity_refs": [_ref().to_dict()],
        "facts": [{"claim_id": "F01", "statement": "贵州茅台存在已提供经营信息。", "source_task_ids": ["T01"]}],
        "analysis": [{"claim_id": "A01", "statement": "可基于已提供证据形成分析。", "source_task_ids": ["T01"]}],
        "uncertainties": [],
        "conclusion": "基于已提供证据完成结构化分析。",
        "source_task_ids": ["T01"],
    }


def test_w09_truncated_json_uses_structural_only_local_repair() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return '{"entity_refs":[],"facts":[{"claim_id":"F01","statement":"截断'
            return json.dumps(_valid_analysis(), ensure_ascii=False)

    llm = FakeLLM()
    result = run_entity_analysis(
        llm,
        _analysis_task(),
        resolved_inputs=_resolved_inputs(),
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert len(llm.calls) == 2
    assert llm.calls[0]["operation"] == "entity.analysis"
    assert llm.calls[1]["operation"] == "schema_repair_structural_only"

    primary_prompt = "\n".join(str(row.get("content") or "") for row in llm.calls[0]["messages"])
    repair_prompt = "\n".join(str(row.get("content") or "") for row in llm.calls[1]["messages"])
    # Same W01 payload is bound to two evidence slots; W09 must not duplicate it.
    assert primary_prompt.count("SECRET_EVIDENCE_MARKER") == 1
    # Repair receives only the failed output/schema context, never the evidence corpus.
    assert "SECRET_EVIDENCE_MARKER" not in repair_prompt
    assert "repair_existing_json_only" in repair_prompt
    assert result.data["slots"]["entity_analysis"]["facts"]
    assert result.completion["expected_task_completed"] is True


def test_w09_local_recovery_exhaustion_is_non_retryable_and_publishes_nothing(tmp_path: Path) -> None:
    class BrokenLLM:
        def generate_text(self, **kwargs):
            return '{"entity_refs":['

    task = _analysis_task()
    result = run_entity_analysis(
        BrokenLLM(), task, resolved_inputs=_resolved_inputs(), language="zh"
    )
    assert result.status == ResultStatus.FAILED
    assert result.error["code"] == "worker_structured_output_failed"
    assert result.error["retryable"] is False
    assert result.metadata["structured_output_local_recovery"] == "exhausted"
    assert result.completion["produced_information_slots"] == []

    store = RunSlotStore(tmp_path)
    assert store.publish_worker_result(task, result) == []
    assert store.read(run_id="run", slot_id="entity_analysis") == []


def test_slot_store_never_publishes_expected_slots_for_failed_or_blocked_results(tmp_path: Path) -> None:
    task = _analysis_task()
    store = RunSlotStore(tmp_path)
    fake_slots = {
        "entity_analysis": {"facts": []},
        "entity_analysis_uncertainty": {"uncertainties": []},
    }
    failed_completion = build_completion_report(
        task,
        execution_status="failed",
        contract_status="not_satisfied",
        business_status="unknown",
        completion_status="not_completed",
        expected_task_completed=False,
        produced_information_slots=[],
        failure_kind="worker_execution_failure",
    )
    failed = GraphWorkerResult(
        task_id="T02",
        agent_id="ENTITY_ANALYST",
        status=ResultStatus.FAILED,
        data={"slots": fake_slots, "produced_information_slots": list(fake_slots)},
        completion=failed_completion,
        focus_refs=[_ref()],
    )
    assert store.publish_worker_result(task, failed) == []

    success_completion = build_completion_report(
        task,
        execution_status="succeeded",
        contract_status="valid",
        business_status="sufficient",
        completion_status="completed",
        expected_task_completed=True,
        produced_information_slots=list(fake_slots),
        failure_kind="none",
    )
    success = GraphWorkerResult(
        task_id="T02",
        agent_id="ENTITY_ANALYST",
        status=ResultStatus.COMPLETED,
        data={"slots": fake_slots, "produced_information_slots": list(fake_slots)},
        completion=success_completion,
        focus_refs=[_ref()],
    )
    published = store.publish_worker_result(task, success)
    assert {row.slot_id for row in published} == set(fake_slots)


def test_blocked_downstream_replan_follows_upstream_retryability() -> None:
    completion = {
        "expected_task_completed": False,
        "failure_kind": "upstream_worker_failed",
    }
    no_retry = flow_decision(ResultStatus.BLOCKED, completion, retryable=False)
    retry = flow_decision(ResultStatus.BLOCKED, completion, retryable=True)
    assert no_retry.replan_recommended is False
    assert retry.replan_recommended is True
