from __future__ import annotations

from rag.reranker import Reranker
from rag.schemas import RetrievalResult


def test_reranker_fallback_uses_hybrid_score() -> None:
    reranker = Reranker()
    reranker.available = False
    candidates = [
        RetrievalResult("chunk_low", "news_001", "普通新闻", hybrid_score=0.1),
        RetrievalResult("chunk_high", "news_002", "回购公告", hybrid_score=0.9),
    ]

    results = reranker.rerank("回购", candidates, top_k=2)

    assert results[0].chunk_id == "chunk_high"
    assert results[0].final_rank == 1
    assert results[0].rerank_score == 0.9


def test_reranker_keeps_only_highest_scoring_chunk_per_document() -> None:
    reranker = Reranker()
    reranker.available = False
    candidates = [
        RetrievalResult("chunk_doc_a_high", "news_a", "公告开头", hybrid_score=0.9),
        RetrievalResult("chunk_doc_a_low", "news_a", "公告结尾", hybrid_score=0.8),
        RetrievalResult("chunk_doc_b", "news_b", "另一篇公告", hybrid_score=0.7),
    ]

    results = reranker.rerank("公告", candidates, top_k=2)

    assert [item.chunk_id for item in results] == ["chunk_doc_a_high", "chunk_doc_b"]
    assert [item.final_rank for item in results] == [1, 2]
