from __future__ import annotations

from pathlib import Path

from agent.capabilities import CapabilityRegistry
from agent.collaboration.context_projection import WorkerInputProjectionMiddleware
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.worker_catalog import WorkerDescriptionCatalog
from agent.collaboration.worker_directory import CapabilityWorkerDirectory
from agent.collaboration.workers.entity_analysis import _entity_analysis_llm_schema
from agent.collaboration.workers.report_writer import run_report_writer
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


def test_worker_catalog_exposes_all_public_descriptions_upfront() -> None:
    catalog = WorkerDescriptionCatalog(CapabilityWorkerDirectory(), CapabilityRegistry())
    descriptions = catalog.descriptions(request_mode="analysis")
    w02 = next(row for row in descriptions if row["worker_id"] == "W02")
    assert "agent_id" not in w02
    assert "delegation_description" in w02
    assert "delegate_when" in w02
    assert "系统内部" in w02["delegation_description"]
    assert "entity_model_signals" in w02["produced_output_slots"]
    assert "market_ranking_signals" in w02["produced_output_slots"]
    assert "model_quality_metrics" in w02["produced_output_slots"]


def test_slot_materialization_uses_bound_producer_and_preserves_nested_payload(tmp_path: Path) -> None:
    store = RunSlotStore(tmp_path)
    nested = {
        "results": [{
            "records": [{
                "title": "贵州茅台公告",
                "metadata": {"a": {"b": {"c": {"d": "preserved"}}}},
            }]
        }]
    }
    store.publish(
        run_id="run", task_id="T01", contract_id="T01-C01",
        slot_id="entity_external_evidence", value=nested,
    )
    task = GraphAgentTask(
        task_id="T02", run_id="run", session_id="s", worker_id="W09",
        assigned_agent="ENTITY_ANALYST", objective="分析", user_id="u",
        boundary_id="entity.analysis",
        contracts=[{
            "contract_id": "T02-C01",
            "required_inputs": [{"slot_id": "entity_external_evidence", "required": True}],
        }],
        resolved_input_bindings=[{
            "source_type": "upstream_task",
            "output_slot_id": "entity_external_evidence",
            "input_slot_id": "entity_external_evidence",
            "producer_task_id": "T01",
            "producer_contract_id": "T01-C01",
        }],
        focus_refs=[_ref()],
    )
    resolved, rows = WorkerInputProjectionMiddleware(store).project(
        task, execution_context={"language": "zh"}
    )
    assert resolved["entity_external_evidence"]["results"][0]["records"][0]["title"] == "贵州茅台公告"
    assert resolved["entity_external_evidence"]["results"][0]["records"][0]["metadata"]["a"]["b"]["c"]["d"] == "preserved"
    assert rows[0].value_ref.startswith("run-slot:run:T01:")


def test_w09_output_schema_has_only_generic_analysis_fields() -> None:
    schema = _entity_analysis_llm_schema()
    props = schema["properties"]
    assert "facts" in props and "analysis" in props and "uncertainties" in props
    assert "model_signals" not in props
    assert "relation_interpretations" not in props


def test_w06_is_text_only_and_runtime_publishes_contract_slots() -> None:
    class FakeLLM:
        def generate_text(self, **kwargs):
            assert kwargs["stage"] == "graph_report_writer"
            return "# 贵州茅台分析\n\n基于已提供的结构化分析结果，当前可确认相关结论。"

    task = GraphAgentTask(
        task_id="T03", run_id="run", session_id="s", worker_id="W06",
        assigned_agent="REPORT_WRITER", objective="生成报告", user_id="u",
        boundary_id="result.composition",
        contracts=[{
            "contract_id": "T03-C01",
            "required_inputs": [{"slot_id": "entity_analysis", "required": True}],
            "promised_outputs": [
                {"slot_id": "user_facing_report"},
                {"slot_id": "goal_completion_summary"},
            ],
        }],
        resolved_input_bindings=[{
            "source_type": "upstream_task",
            "output_slot_id": "entity_analysis",
            "input_slot_id": "entity_analysis",
            "producer_task_id": "T02",
            "producer_contract_id": "T02-C01",
        }],
        expected_output_slots=["user_facing_report", "goal_completion_summary"],
        focus_refs=[_ref()],
    )
    result = run_report_writer(
        FakeLLM(), task, "zh",
        resolved_inputs={
            "entity_analysis": {
                "facts": [{"claim_id": "F1", "statement": "已提供事实", "source_task_ids": ["T02"]}],
                "analysis": [], "uncertainties": [], "conclusion": "结论", "source_task_ids": ["T02"],
            }
        },
    )
    assert result.status == ResultStatus.COMPLETED
    assert result.data["content"].startswith("# 贵州茅台分析")
    assert result.data["slots"]["user_facing_report"] == result.data["content"]
    assert result.data["slots"]["goal_completion_summary"]["source_task_ids"] == ["T02"]
    assert result.metadata["natural_language_output"] is True
