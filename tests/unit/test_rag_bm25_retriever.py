from __future__ import annotations

from rag.bm25_retriever import BM25Retriever
from rag.schemas import RagChunk


def test_bm25_retrieves_keyword_chunk() -> None:
    chunks = [
        RagChunk(
            chunk_id="chunk_001",
            news_id="news_001",
            chunk_index=0,
            chunk_text="公司公告称拟回购股份并稳定投资者预期。",
            stock_codes=["000001"],
            trade_date="2026-06-11",
        ),
        RagChunk(
            chunk_id="chunk_002",
            news_id="news_002",
            chunk_index=0,
            chunk_text="行业日常经营情况平稳。",
            stock_codes=["000002"],
            trade_date="2026-06-11",
        ),
    ]
    retriever = BM25Retriever(financial_terms=["回购", "000001"]).build_index(chunks)

    results = retriever.search("回购", top_k=3)

    assert results
    assert results[0].chunk_id == "chunk_001"
    assert results[0].bm25_score > 0


def test_bm25_metadata_filter_limits_stock() -> None:
    chunks = [
        RagChunk("chunk_001", "news_001", 0, "宁德时代出现风险提示。", stock_codes=["300750"]),
        RagChunk("chunk_002", "news_002", 0, "贵州茅台出现风险提示。", stock_codes=["600519"]),
    ]
    retriever = BM25Retriever(financial_terms=["宁德时代", "贵州茅台"]).build_index(chunks)

    results = retriever.search("风险提示", top_k=5, metadata_filter={"stock_code": "300750"})

    assert [item.chunk_id for item in results] == ["chunk_001"]
