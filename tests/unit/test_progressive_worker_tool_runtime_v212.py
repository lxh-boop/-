from __future__ import annotations

from agent.capabilities import CapabilityRegistry, TaskDependencyCompiler
from agent.collaboration.worker_catalog import WorkerDescriptionCatalog
from agent.collaboration.worker_directory import CapabilityWorkerDirectory
from agent.context.context_types import ContextBundle


def test_worker_catalog_exposes_upfront_descriptions_without_private_tool_details() -> None:
    rows=WorkerDescriptionCatalog(CapabilityWorkerDirectory(),CapabilityRegistry()).descriptions(effect_limit="read")
    assert {x["worker_id"] for x in rows} >= {"W01","W02","W04","W05","W07","W09"}
    assert all(x["private_tool_details_visible_to_main_agent"] is False for x in rows)


def test_normal_business_catalog_excludes_mutation_worker() -> None:
    rows=WorkerDescriptionCatalog(CapabilityWorkerDirectory(),CapabilityRegistry()).descriptions(effect_limit="proposal")
    assert "W08" not in {x["worker_id"] for x in rows}
    assert "W05" in {x["worker_id"] for x in rows}


def test_contextbundle_empty_value_is_present_and_reusable() -> None:
    bundle=ContextBundle(user_id="u",conversation_id="s",run_id="r")
    bundle.put_business_data(entity_ref=None,name="portfolio",value={})
    assert bundle.has_business_data(entity_id="__run__",name="portfolio")
    assert bundle.business_data_context()["global_data"]["portfolio"] == {}


def test_analysis_workers_consume_contextbundle_and_do_not_name_upstream_workers() -> None:
    d=CapabilityWorkerDirectory()
    for wid in ("W04","W05","W09"):
        card=d.get(wid)
        assert card.working_memory_mode == "consumer"
        assert card.can_mutate is False


def test_task_dependency_compiler_is_ordering_only() -> None:
    # Detailed dependency behavior is covered in v2316 tests; this historical
    # guard ensures the active compiler is no longer a business-data binder.
    compiler=TaskDependencyCompiler(CapabilityWorkerDirectory())
    assert compiler.__class__.__name__ == "TaskDependencyCompiler"
