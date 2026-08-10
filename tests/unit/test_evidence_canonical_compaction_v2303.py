from __future__ import annotations

import json
from types import SimpleNamespace

from agent.capabilities.semantic_slots import estimate_json_chars, estimate_tokens
from agent.collaboration.models import GraphAgentTask, ResultStatus
from agent.collaboration.workers.entity_analysis import run_entity_analysis
from agent.collaboration.workers.evidence import run_evidence
from agent.graph.contracts import GraphNodeKind, GraphRef


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


def _large_records() -> list[dict]:
    rows: list[dict] = []
    for index in range(15):
        is_news = index < 10
        body = f"BODY_{index}_" + ("正文" * 1800)
        row = {
            "canonical_id": f"e-{index}",
            "source_ids": [f"e-{index}"],
            "source_id": f"e-{index}",
            "chunk_id": f"chunk-{index}" if not is_news else "",
            "source_type": "news" if is_news else "rag_chunk",
            "provider_type": "news_event" if is_news else "rag_chunk",
            "source": "unit-source",
            "title": f"证据{index}",
            "publish_time": "2026-08-10T09:00:00",
            "url": f"https://example.test/{index}",
            "event_type": "earnings" if is_news else "research",
            "sentiment": "positive",
            "importance_score": 0.9,
            "mapping_confidence": 0.88,
            "impact_direction": "positive",
            "impact_strength": 0.7,
            "score": 0.95,
            "retrieved_by": ["news_and_announcements" if is_news else "rag_evidence"],
            "merged_record_count": 1,
            # Deliberately duplicate the same long body in multiple Tool-internal
            # representations. Cross-Worker transport must normalize these.
            "text": body,
            "content": body,
            "chunk_text": body,
            "bm25_score": 0.41,
            "dense_score": 0.52,
            "hybrid_score": 0.63,
            "rerank_score": 0.74,
            "retrieval_backend": "bm25_dense_rrf_reranker",
        }
        if is_news:
            row["summary"] = f"NEWS_SUMMARY_{index}_" + ("摘要" * 80)
        rows.append(row)
    return rows


def _final_data() -> dict:
    records = _large_records()
    return {
        "validated_evidence_collection": True,
        "results": [
            {
                "focus_ref": _ref().to_dict(),
                "success": True,
                "message": "Evidence collected.",
                "records": records,
                "sources": [
                    {
                        "source_type": row["source_type"],
                        "source_id": row["source_id"],
                        "title": row["title"],
                        "source": row["source"],
                        "url": row["url"],
                    }
                    for row in records
                ],
                "source_names": ["news_and_announcements", "rag_evidence"],
                "deduplication": {"duplicate_groups": []},
                "warnings": [],
                "errors": [],
            }
        ],
        "record_count": 15,
        "source_count": 15,
        "deduplication": {
            "policy": "shared_identity_value",
            "raw_record_count": 15,
            "identified_record_count": 15,
            "unidentified_record_count": 0,
            "canonical_record_count": 15,
            "duplicate_record_count": 0,
            "duplicate_group_count": 0,
            "cross_source_duplicate_group_count": 0,
            "source_record_counts": {
                "news_and_announcements": 10,
                "rag_evidence": 5,
            },
            "duplicate_groups": [],
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


def _w01_task(outputs: list[str] | None = None) -> GraphAgentTask:
    outputs = outputs or ["entity_external_evidence", "evidence_source_records"]
    return GraphAgentTask(
        task_id="T01",
        run_id="run-v2303",
        session_id="session",
        worker_id="W01",
        assigned_agent="EVIDENCE_COLLECTOR",
        objective="分析贵州茅台",
        user_id="u",
        boundary_id="external_evidence.research",
        contracts=[
            {
                "contract_id": "T01-C01",
                "required_inputs": [{"slot_id": "authoritative_entity_refs", "required": True}],
                "promised_outputs": [{"slot_id": slot_id} for slot_id in outputs],
                "acceptance_rule_ids": ["schema_valid"],
                "allowed_terminal_states": ["completed", "business_empty", "business_insufficient"],
            }
        ],
        expected_output_slots=outputs,
        focus_refs=[_ref()],
        metadata={
            "authoritative_entity_catalog": [
                {
                    "node_id": _ref().node_id,
                    "public_code": "600519",
                    "display_label": "贵州茅台",
                }
            ]
        },
    )


class _Runtime:
    def run(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            success=True,
            final_results=[SimpleNamespace(data=_final_data())],
            node_records=[],
            final_output_task_ids=["task_finalize"],
            plan=SimpleNamespace(tasks=[SimpleNamespace(tool_task_id="task_finalize")]),
            execution_batches=[["task_finalize"]],
            replan_count=0,
        )


def test_entity_external_evidence_is_compact_analysis_transport(tmp_path) -> None:
    result = run_evidence(
        _Runtime(),
        _w01_task(),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[],
    )
    assert result.status == ResultStatus.COMPLETED
    canonical = result.data["slots"]["entity_external_evidence"]
    rows = canonical["results"][0]["records"]

    assert len(rows) == 15  # no evidence record is dropped
    assert canonical["record_count"] == 15
    assert canonical["projection"]["kind"] == "analysis_canonical_evidence"
    assert canonical["projection"]["body_policy"] == "single_bounded_text"
    assert canonical["projection"]["text_limit_chars"] == 1000

    # Cross-Worker payload keeps exactly one normalized body representation.
    for row in rows:
        assert "text" in row
        assert "content" not in row
        assert "chunk_text" not in row
        assert "summary" not in row
        assert "bm25_score" not in row
        assert "dense_score" not in row
        assert "hybrid_score" not in row
        assert "rerank_score" not in row
        assert "retrieval_backend" not in row
        assert row["canonical_id"]
        assert row["retrieved_by"]
        assert row["source_id"]
        assert row["title"]
        assert row["source"]
        assert row["publish_time"]

    # News prefers its compact summary. RAG keeps one bounded chunk body.
    assert rows[0]["text"].startswith("NEWS_SUMMARY_0_")
    assert rows[0]["text_source_field"] == "summary"
    rag_row = rows[-1]
    assert rag_row["text_source_field"] == "text"
    assert rag_row["text_truncated"] is True
    assert rag_row["text_original_chars"] > 1000
    assert len(rag_row["text"]) <= 1000

    # Keep the runtime projection safely below SLOT_OVERSIZED's 8k-token audit threshold.
    assert estimate_json_chars(canonical) < 32000
    assert estimate_tokens(canonical) < 8000


def test_source_specific_views_use_same_compact_record_contract(tmp_path) -> None:
    result = run_evidence(
        _Runtime(),
        _w01_task(["evidence.news", "evidence.research"]),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[],
    )
    news = result.data["slots"]["evidence.news"]
    research = result.data["slots"]["evidence.research"]
    assert news["record_count"] == 10
    assert research["record_count"] == 5
    for payload in (news, research):
        for row in payload["results"][0]["records"]:
            assert "content" not in row
            assert "chunk_text" not in row
            assert "text" in row


def test_w09_preserves_canonical_ids_and_business_metadata_in_prompt(tmp_path) -> None:
    w01 = run_evidence(
        _Runtime(),
        _w01_task(["entity_external_evidence"]),
        "分析贵州茅台",
        tmp_path,
        None,
        20,
        worker_prompt="collect evidence",
        allowed_tool_names=[],
    )
    task = GraphAgentTask(
        task_id="T02",
        run_id="run-v2303",
        session_id="session",
        worker_id="W09",
        assigned_agent="ENTITY_ANALYST",
        objective="分析贵州茅台",
        user_id="u",
        boundary_id="entity.analysis",
        contracts=[
            {
                "contract_id": "T02-C01",
                "required_inputs": [{"slot_id": "entity_external_evidence", "required": True}],
                "promised_outputs": [
                    {"slot_id": "entity_analysis"},
                    {"slot_id": "entity_analysis_uncertainty"},
                ],
                "allowed_terminal_states": ["completed"],
            }
        ],
        resolved_input_bindings=[
            {
                "source_type": "upstream_task",
                "output_slot_id": "entity_external_evidence",
                "input_slot_id": "entity_external_evidence",
                "producer_task_id": "T01",
                "producer_contract_id": "T01-C01",
            }
        ],
        expected_output_slots=["entity_analysis", "entity_analysis_uncertainty"],
        focus_refs=[_ref()],
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
                            "statement": "存在已提供证据。",
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
        task,
        resolved_inputs={"entity_external_evidence": w01.data["slots"]["entity_external_evidence"]},
        language="zh",
    )
    assert result.status == ResultStatus.COMPLETED
    prompt = "\n".join(str(item.get("content") or "") for item in llm.calls[0]["messages"])
    assert '"canonical_id":"e-0"' in prompt
    assert '"event_type":"earnings"' in prompt
    assert '"impact_direction":"positive"' in prompt
    assert "retrieval_backend" not in prompt
    assert "bm25_score" not in prompt
