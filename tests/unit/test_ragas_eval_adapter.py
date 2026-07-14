from __future__ import annotations

from evaluation.ragas_eval.rag_adapter import ProjectRagAdapter
from evaluation.ragas_eval.schemas import EvaluationCase
from rag.schemas import RetrievalResult


class FakeRetriever:
    def __init__(self) -> None:
        self.built_chunks = None
        self.last_filter = None

    def build_index(self, chunks):
        self.built_chunks = list(chunks)
        return self

    def search(self, query, final_top_k=10, metadata_filter=None):
        self.last_filter = metadata_filter
        return [
            RetrievalResult(
                chunk_id="chunk_1",
                news_id="news_1",
                chunk_text="公司公告正文。",
                bm25_score=1.0,
                hybrid_score=0.9,
                rerank_score=0.8,
                final_rank=1,
                metadata={
                    "news_id": "news_1",
                    "stock_code": "300750",
                    "publish_time": "2026-06-20 10:00:00",
                    "source": "上市公司公告",
                    "section_title": "公告摘要",
                },
            ),
            RetrievalResult(
                chunk_id="chunk_1",
                news_id="news_1",
                chunk_text="重复。",
                final_rank=2,
                metadata={"news_id": "news_1"},
            ),
            RetrievalResult(
                chunk_id="chunk_2",
                news_id="news_2",
                chunk_text="第二条。",
                dense_score=0.7,
                hybrid_score=0.6,
                final_rank=3,
                metadata={"document_id": "doc_2", "stock_codes": ["300750"], "publish_time": "2026-06-19 10:00:00"},
            ),
        ]


def test_project_rag_adapter_preserves_rank_converts_fields_and_dedupes() -> None:
    fake = FakeRetriever()
    adapter = ProjectRagAdapter(chunks=[], retriever=fake)
    case = EvaluationCase.from_mapping({
        "case_id": "case_1",
        "user_input": "公告风险",
        "stock_code": "300750.SZ",
        "decision_time": "2026-06-20T15:00:00+08:00",
        "reference_context_ids": [],
    })

    contexts, metadata = adapter.retrieve(case, top_k=3)

    assert fake.last_filter["decision_time"] == "2026-06-20 15:00:00"
    assert fake.last_filter["stock_code"] == "300750"
    assert [item.chunk_id for item in contexts] == ["chunk_1", "chunk_2"]
    assert [item.rank for item in contexts] == [1, 3]
    assert contexts[0].document_id == "news_1"
    assert contexts[0].title == "公告摘要"
    assert contexts[0].stock_codes == ["300750"]
    assert contexts[0].retrieval_sources == ["bm25", "hybrid", "reranker"]
    assert contexts[1].document_id == "doc_2"
    assert "duplicate retrieved chunk_id=chunk_1" in " ".join(metadata["warnings"])
