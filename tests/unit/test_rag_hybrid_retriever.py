from __future__ import annotations

from rag.bm25_retriever import BM25Retriever
from rag.dense_retriever import DenseRetriever
from rag.hybrid_retriever import HybridRetriever
from rag.reranker import Reranker
from rag.schemas import RagChunk


def test_hybrid_retrieval_works_when_dense_unavailable() -> None:
    chunks = [
        RagChunk("chunk_001", "news_001", 0, "公司发布回购股份公告。", stock_codes=["000001"]),
        RagChunk("chunk_002", "news_002", 0, "天气晴朗。", stock_codes=["000002"]),
    ]
    dense = DenseRetriever()
    dense.available = False
    retriever = HybridRetriever(
        bm25=BM25Retriever(financial_terms=["回购"]),
        dense=dense,
        reranker=Reranker(),
    ).build_index(chunks)

    results = retriever.search("回购 股份", final_top_k=5)

    assert results
    assert results[0].chunk_id == "chunk_001"
    assert results[0].hybrid_score > 0
