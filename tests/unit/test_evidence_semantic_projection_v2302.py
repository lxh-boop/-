from __future__ import annotations

import json
from types import SimpleNamespace

from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.collaboration.workers.evidence import run_evidence
from agent.graph.contracts import GraphNodeKind, GraphRef
from agent.worker_tools.evidence import (
    EVIDENCE_FINALIZE_COLLECTION_TOOL,
    build_evidence_tool_definitions,
)


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


def _canonical_results() -> list[dict]:
    return [
        {
            "focus_ref": _ref().to_dict(),
            "success": True,
            "message": "Evidence collected.",
            "source_names": ["news_and_announcements", "rag_evidence"],
            "records": [
                {
                    "canonical_id": "news-1",
                    "source_ids": ["news-1"],
                    "source_id": "news-1",
                    "source_type": "news",
                    "source": "unit-news",
                    "title": "新闻证据",
                    "text": "NEWS_ONLY_MARKER 新闻正文",
                    "date": "2026-08-09",
                    "retrieved_by": ["news_and_announcements"],
                    "merged_record_count": 1,
                },
                {
                    "canonical_id": "rag-1",
                    "source_ids": ["rag-1"],
                    "source_id": "rag-1",
                    "source_type": "rag_chunk",
                    "provider_type": "rag_chunk",
                    "source": "unit-rag",
                    "title": "研究证据",
                    "text": "RAG_ONLY_MARKER 研究正文",
                    "date": "2026-08-08",
                    "retrieved_by": ["rag_evidence"],
                    "merged_record_count": 1,
                },
                {
                    "canonical_id": "shared-1",
                    "source_ids": ["shared-1"],
                    "source_id": "shared-1",
                    "source_type": "news",
                    "source": "unit-shared",
                    "title": "交叉来源证据",
                    "text": "SHARED_MARKER 同时被新闻和RAG检索到",
                    "date": "2026-08-07",
                    "retrieved_by": ["news_and_announcements", "rag_evidence"],
                    "merged_record_count": 2,
                },
            ],
            "sources": [],
            "deduplication": {},
            "warnings": [],
            "errors": [],
        }
    ]


def _w01_task() -> GraphAgentTask:
    return GraphAgentTask(
        task_id="T01",
        run_id="run-v2302",
        session_id="session",
        worker_id="W01",
        assigned_agent="EVIDENCE_COLLECTOR",
        objective="收集贵州茅台证据",
        user_id="u",
        boundary_id="external_evidence.research",
        contracts=[
            {
                "contract_id": "T01-C01",
                "required_inputs": [
                    {"slot_id": "authoritative_entity_refs", "required": True}
                ],
                "promised_outputs": [
                    {"slot_id": "entity_external_evidence"},
                    {"slot_id": "evidence_source_records"},
                    {"slot_id": "evidence.news"},
                    {"slot_id": "evidence.research"},
                ],
                "acceptance_rule_ids": ["schema_valid"],
                "allowed_terminal_states": [
                    "completed",
                    "business_empty",
                    "business_insufficient",
                ],
            }
        ],
        expected_output_slots=[
            "entity_external_evidence",
            "evidence_source_records",
            "evidence.news",
            "evidence.research",
        ],
        focus_refs=[_ref()],
        metadata={
            "authoritative_entity_catalog": [
                {
                    "node_id": "cn:security:sse:600519",
                    "public_code": "600519",
                    "display_label": "贵州茅台",
                }
            ]
        },
    )


class _FakeToolDagRuntime:
    def run(self, **kwargs):
        del kwargs
        final_data = {
            "validated_evidence_collection": True,
            "results": _canonical_results(),
            "record_count": 3,
            "source_count": 3,
            "deduplication": {
                "policy": "shared_identity_value",
                "canonical_record_count": 3,
                "source_record_counts": {
                    "news_and_announcements": 2,
                    "rag_evidence": 2,
                },
            },
            "coverage": {
                "required_entity_count": 1,
                "covered_entity_count": 1,
                "missing_entity_ref_ids": [],
                "coverage_satisfied": True,
            },
            "business_empty": False,
            "warnings": [],
            "errors": [],
        }
        return SimpleNamespace(
            success=True,
            final_results=[SimpleNamespace(data=final_data)],
            node_records=[],
            final_output_task_ids=["task_finalize"],
            plan=SimpleNamespace(tasks=[SimpleNamespace(tool_task_id="task_finalize")]),
            execution_batches=[["task_finalize"]],
            replan_count=0,
        )


def test_w01_publishes_four_distinct_semantic_evidence_slots(tmp_path) -> None:
    result = run_evidence(
        _FakeToolDagRuntime(),
        _w01_task(),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[
            "evidence.search_news",
            "evidence.search_rag",
            "evidence.finalize_collection",
        ],
    )
    assert result.status == ResultStatus.COMPLETED
    slots = result.data["slots"]
    assert set(slots) == {
        "entity_external_evidence",
        "evidence_source_records",
        "evidence.news",
        "evidence.research",
    }

    canonical = slots["entity_external_evidence"]
    source_index = slots["evidence_source_records"]
    news = slots["evidence.news"]
    research = slots["evidence.research"]

    assert canonical["record_count"] == 3
    assert news["record_count"] == 2
    assert research["record_count"] == 2
    assert news["retrieval_sources"] == ["news_and_announcements"]
    assert research["retrieval_sources"] == ["rag_evidence"]

    news_ids = {row["canonical_id"] for row in news["results"][0]["records"]}
    research_ids = {row["canonical_id"] for row in research["results"][0]["records"]}
    assert news_ids == {"news-1", "shared-1"}
    assert research_ids == {"rag-1", "shared-1"}

    # Provenance index keeps source identity but never repeats evidence body text.
    index_json = json.dumps(source_index, ensure_ascii=False, sort_keys=True)
    canonical_json = json.dumps(canonical, ensure_ascii=False, sort_keys=True)
    assert "NEWS_ONLY_MARKER" not in index_json
    assert "RAG_ONLY_MARKER" not in index_json
    assert "SHARED_MARKER" not in index_json
    assert len(index_json) < len(canonical_json)

    # Four semantic slots are not copies of the same serialized payload.
    serialized = {
        slot_id: json.dumps(value, ensure_ascii=False, sort_keys=True)
        for slot_id, value in slots.items()
    }
    assert len(set(serialized.values())) == 4


def _w09_task_all_evidence_views() -> GraphAgentTask:
    required_slots = [
        "authoritative_entity_refs",
        "entity_external_evidence",
        "evidence_source_records",
        "evidence.news",
        "evidence.research",
    ]
    bindings = [
        {
            "source_type": "runtime_context",
            "output_slot_id": "authoritative_entity_refs",
            "input_slot_id": "authoritative_entity_refs",
        }
    ]
    for slot_id in required_slots[1:]:
        bindings.append(
            {
                "source_type": "upstream_task",
                "output_slot_id": slot_id,
                "input_slot_id": slot_id,
                "producer_task_id": "T01",
                "producer_contract_id": "T01-C01",
            }
        )
    return GraphAgentTask(
        task_id="T02",
        run_id="run-v2302",
        session_id="session",
        worker_id="W09",
        assigned_agent="ENTITY_ANALYST",
        objective="分析贵州茅台",
        user_id="u",
        boundary_id="entity.analysis",
        contracts=[
            {
                "contract_id": "T02-C01",
                "required_inputs": [
                    {"slot_id": slot_id, "required": True}
                    for slot_id in required_slots
                ],
                "promised_outputs": [
                    {"slot_id": "entity_analysis"},
                    {"slot_id": "entity_analysis_uncertainty"},
                    {"slot_id": "analysis.entity"},
                ],
                "allowed_terminal_states": ["completed"],
            }
        ],
        resolved_input_bindings=bindings,
        expected_output_slots=[
            "entity_analysis",
            "entity_analysis_uncertainty",
            "analysis.entity",
        ],
        focus_refs=[_ref()],
        metadata={
            "authoritative_entity_catalog": [
                {"node_id": "cn:security:sse:600519", "display_label": "贵州茅台"}
            ]
        },
    )


def _resolved_w09_inputs_from_w01(slots: dict) -> dict:
    return {
        "authoritative_entity_refs": [_ref().to_dict()],
        **slots,
    }


def test_w09_consumes_canonical_evidence_once_when_same_w01_also_bound_views(tmp_path) -> None:
    w01 = run_evidence(
        _FakeToolDagRuntime(),
        _w01_task(),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[],
    )

    class FakeLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps(
                {
                    "entity_refs": [_ref().to_dict()],
                    "facts": [
                        {
                            "claim_id": "F01",
                            "statement": "存在已提供的外部证据。",
                            "source_task_ids": ["T01"],
                        }
                    ],
                    "analysis": [],
                    "uncertainties": [],
                    "conclusion": "完成分析。",
                    "source_task_ids": ["T01"],
                },
                ensure_ascii=False,
            )

    llm = FakeLLM()
    result = run_entity_analysis(
        llm,
        _w09_task_all_evidence_views(),
        resolved_inputs=_resolved_w09_inputs_from_w01(w01.data["slots"]),
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    assert len(llm.calls) == 1
    prompt = "\n".join(str(row.get("content") or "") for row in llm.calls[0]["messages"])

    # Canonical collection is compacted once. Derivative views from the same W01
    # are valid runtime Slots but are deliberately omitted from W09's LLM prompt.
    assert prompt.count("NEWS_ONLY_MARKER") == 1
    assert prompt.count("RAG_ONLY_MARKER") == 1
    assert prompt.count("SHARED_MARKER") == 1
    assert "payload_alias_of" not in prompt
    assert result.metadata["suppressed_redundant_evidence_slots"] == [
        "evidence_source_records",
        "evidence.news",
        "evidence.research",
    ]


def test_w09_can_still_analyze_news_view_when_canonical_slot_is_not_bound() -> None:
    task = _w09_task_all_evidence_views()
    task.contracts[0]["required_inputs"] = [
        {"slot_id": "authoritative_entity_refs", "required": True},
        {"slot_id": "evidence.news", "required": True},
    ]
    task.resolved_input_bindings = [
        task.resolved_input_bindings[0],
        next(
            row for row in task.resolved_input_bindings
            if row.get("input_slot_id") == "evidence.news"
        ),
    ]
    news_payload = {
        "entity_refs": [_ref().to_dict()],
        "results": [
            {
                "focus_ref": _ref().to_dict(),
                "source_names": ["news_and_announcements"],
                "records": [
                    {
                        "canonical_id": "news-only",
                        "source": "unit-news",
                        "title": "新闻",
                        "text": "NEWS_VIEW_ONLY_MARKER",
                        "retrieved_by": ["news_and_announcements"],
                    }
                ],
                "sources": [],
                "warnings": [],
                "errors": [],
            }
        ],
        "record_count": 1,
        "source_count": 1,
        "coverage": {"coverage_satisfied": True},
        "deduplication": {},
        "business_empty": False,
    }

    class FakeLLM:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def generate_text(self, **kwargs):
            self.calls.append(kwargs)
            return json.dumps(
                {
                    "entity_refs": [_ref().to_dict()],
                    "facts": [
                        {
                            "claim_id": "F01",
                            "statement": "存在新闻证据。",
                            "source_task_ids": ["T01"],
                        }
                    ],
                    "analysis": [],
                    "uncertainties": [],
                    "conclusion": "完成新闻分析。",
                    "source_task_ids": ["T01"],
                },
                ensure_ascii=False,
            )

    llm = FakeLLM()
    result = run_entity_analysis(
        llm,
        task,
        resolved_inputs={
            "authoritative_entity_refs": [_ref().to_dict()],
            "evidence.news": news_payload,
        },
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    prompt = "\n".join(str(row.get("content") or "") for row in llm.calls[0]["messages"])
    assert "NEWS_VIEW_ONLY_MARKER" in prompt
    assert result.metadata["suppressed_redundant_evidence_slots"] == []


def test_real_finalizer_provenance_drives_news_and_research_views(tmp_path) -> None:
    class FakeProvider:
        pass

    definitions = build_evidence_tool_definitions(FakeProvider())
    finalizer = next(
        item for item in definitions if item.name == EVIDENCE_FINALIZE_COLLECTION_TOOL
    )
    ref = _ref().to_dict()
    news_collection = {
        "results": [
            {
                "focus_ref": ref,
                "source_name": "news_and_announcements",
                "success": True,
                "records": [
                    {
                        "source_id": "news-real",
                        "source_type": "news",
                        "title": "新闻来源",
                        "text": "REAL_NEWS_MARKER",
                    }
                ],
                "sources": [],
                "warnings": [],
                "errors": [],
            }
        ],
        "source_name": "news_and_announcements",
    }
    rag_collection = {
        "results": [
            {
                "focus_ref": ref,
                "source_name": "rag_evidence",
                "success": True,
                "records": [
                    {
                        "source_id": "rag-real",
                        "source_type": "rag_chunk",
                        "title": "RAG来源",
                        "text": "REAL_RAG_MARKER",
                    }
                ],
                "sources": [],
                "warnings": [],
                "errors": [],
            }
        ],
        "source_name": "rag_evidence",
    }
    finalized = finalizer.execution_handler(
        {
            "collections": [news_collection, rag_collection],
            "required_object_refs": [ref],
        },
        {},
    )
    final_data = finalized["data"]
    retrieved_by = {
        row["source_id"]: row["retrieved_by"]
        for row in final_data["results"][0]["records"]
    }
    assert retrieved_by == {
        "news-real": ["news_and_announcements"],
        "rag-real": ["rag_evidence"],
    }

    class RuntimeFromFinalizer:
        def run(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                success=True,
                final_results=[SimpleNamespace(data=final_data)],
                node_records=[],
                final_output_task_ids=["task_finalize"],
                plan=SimpleNamespace(tasks=[SimpleNamespace(tool_task_id="task_finalize")]),
                execution_batches=[["task_finalize"]],
                replan_count=0,
            )

    result = run_evidence(
        RuntimeFromFinalizer(),
        _w01_task(),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[],
    )
    slots = result.data["slots"]
    assert slots["evidence.news"]["record_count"] == 1
    assert slots["evidence.research"]["record_count"] == 1
    assert slots["evidence.news"]["results"][0]["records"][0]["source_id"] == "news-real"
    assert slots["evidence.research"]["results"][0]["records"][0]["source_id"] == "rag-real"


def test_news_only_contract_reports_business_empty_when_only_rag_exists(tmp_path) -> None:
    rag_only_results = [
        {
            "focus_ref": _ref().to_dict(),
            "success": True,
            "message": "Evidence collected.",
            "source_names": ["rag_evidence"],
            "records": [
                {
                    "canonical_id": "rag-only",
                    "source_ids": ["rag-only"],
                    "source_id": "rag-only",
                    "source_type": "rag_chunk",
                    "title": "研究证据",
                    "text": "RAG_ONLY",
                    "retrieved_by": ["rag_evidence"],
                }
            ],
            "sources": [],
            "warnings": [],
            "errors": [],
        }
    ]
    final_data = {
        "validated_evidence_collection": True,
        "results": rag_only_results,
        "record_count": 1,
        "source_count": 1,
        "deduplication": {},
        "coverage": {
            "required_entity_count": 1,
            "covered_entity_count": 1,
            "missing_entity_ref_ids": [],
            "coverage_satisfied": True,
        },
        "business_empty": False,
        "warnings": [],
        "errors": [],
    }

    class RagOnlyRuntime:
        def run(self, **kwargs):
            del kwargs
            return SimpleNamespace(
                success=True,
                final_results=[SimpleNamespace(data=final_data)],
                node_records=[],
                final_output_task_ids=["task_finalize"],
                plan=SimpleNamespace(tasks=[SimpleNamespace(tool_task_id="task_finalize")]),
                execution_batches=[["task_finalize"]],
                replan_count=0,
            )

    task = _w01_task()
    task.contracts[0]["promised_outputs"] = [{"slot_id": "evidence.news"}]
    task.expected_output_slots = ["evidence.news"]
    result = run_evidence(
        RagOnlyRuntime(),
        task,
        "最近有什么新闻",
        tmp_path,
        None,
        20,
        worker_prompt="collect news",
        allowed_tool_names=[],
    )
    assert result.status == ResultStatus.COMPLETED
    assert result.data["slots"]["evidence.news"]["business_empty"] is True
    assert result.completion["business_status"] == "empty"
    assert result.completion["expected_task_completed"] is True
