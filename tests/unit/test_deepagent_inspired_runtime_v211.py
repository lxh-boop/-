from __future__ import annotations

from agent.capabilities import CapabilityRegistry
from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.worker_catalog import WorkerDescriptionCatalog
from agent.collaboration.worker_directory import CapabilityWorkerDirectory
from agent.collaboration.workers.entity_analysis import _analysis_schema
from agent.collaboration.workers.report_writer import run_report_writer
from agent.context.context_types import ContextBundle
from agent.graph.contracts import GraphNodeKind, GraphRef


def _ref():
    return GraphRef(graph_id="financial_graph",node_id="cn:security:sse:600519",node_kind=GraphNodeKind.OBJECT,role="focus",source="test",confidence=1.0,locked=True)


def test_worker_catalog_exposes_public_descriptions_and_simple_data_names() -> None:
    rows=WorkerDescriptionCatalog(CapabilityWorkerDirectory(),CapabilityRegistry()).descriptions(effect_limit="read")
    w02=next(x for x in rows if x["worker_id"]=="W02")
    assert "agent_id" not in w02
    assert {"prediction","ranking"}.issubset(set(w02["output_data_examples"]))
    assert w02["working_memory_mode"] == "provider"


def test_contextbundle_preserves_nested_successful_business_data() -> None:
    bundle=ContextBundle(user_id="u",conversation_id="s",run_id="r")
    nested={"results":[{"records":[{"title":"贵州茅台公告","metadata":{"a":{"b":{"c":{"d":"preserved"}}}}}]}]}
    bundle.put_business_data(entity_ref=_ref().to_dict(),name="evidence",value=nested)
    view=bundle.business_data_context(entity_refs=[_ref().to_dict()])
    assert view["entities"][0]["data"]["evidence"]["results"][0]["records"][0]["metadata"]["a"]["b"]["c"]["d"] == "preserved"


def test_w09_output_schema_has_only_generic_analysis_fields() -> None:
    props=_analysis_schema()["properties"]
    assert {"context_sufficient","missing_information","facts","analysis","uncertainties","conclusion"}.issubset(props)
    assert "model_signals" not in props and "relation_interpretations" not in props


def test_w06_reads_request_results_directly_and_publishes_report_data_names() -> None:
    class LLM:
        def generate_text(self, **kwargs): return "# 汇总\n\n已完成。"
    c=AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator); c.directory=CapabilityWorkerDirectory()
    task=c._build_bundle_report_task(run_id="r",session_id="s",user_id="u",objective="汇总")
    result=run_report_writer(LLM(),task,"zh",request_bundle_results={"R01":{"status":"completed"}},presentation_policy={})
    assert result.status == ResultStatus.COMPLETED
    assert result.data["business_data"]["report"].startswith("# 汇总")
    assert result.data["produced_data_names"] == ["report","result.user_facing"]
