from __future__ import annotations

from typing import Any

from rag.bm25_retriever import BM25Retriever
from rag.dense_retriever import DenseRetriever
from rag.reranker import Reranker
from rag.schemas import RagChunk, RetrievalResult


DEFAULT_RERANK_CANDIDATES = 40


class HybridRetriever:
    def __init__(
        self,
        bm25: BM25Retriever | None = None,
        dense: DenseRetriever | None = None,
        reranker: Reranker | None = None,
        rrf_k: int = 60,
    ):
        self.bm25 = bm25 or BM25Retriever()
        self.dense = dense or DenseRetriever()
        self.reranker = reranker or Reranker()
        self.rrf_k = int(rrf_k)

    def build_index(self, chunks: list[RagChunk | dict[str, Any]]) -> "HybridRetriever":
        self.bm25.build_index(chunks)
        self.dense.build_index(chunks)
        return self

    def search(
        self,
        query: str,
        bm25_top_k: int = 50,
        dense_top_k: int = 50,
        merged_top_k: int = DEFAULT_RERANK_CANDIDATES,
        final_top_k: int = 10,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        bm25_results = self.bm25.search(query, top_k=bm25_top_k, metadata_filter=metadata_filter)
        dense_results = self.dense.search(query, top_k=dense_top_k, metadata_filter=metadata_filter)

        by_id: dict[str, dict[str, Any]] = {}

        for rank, item in enumerate(bm25_results, start=1):
            row = by_id.setdefault(item.chunk_id, item.to_dict())
            row["bm25_score"] = item.bm25_score
            row["_rrf_score"] = float(row.get("_rrf_score", 0.0)) + 1.0 / (self.rrf_k + rank)

        for rank, item in enumerate(dense_results, start=1):
            row = by_id.setdefault(item.chunk_id, item.to_dict())
            row["dense_score"] = item.dense_score
            row["_rrf_score"] = float(row.get("_rrf_score", 0.0)) + 1.0 / (self.rrf_k + rank)

        merged = []
        for row in by_id.values():
            row["hybrid_score"] = float(row.pop("_rrf_score", 0.0))
            merged.append(RetrievalResult(**row))

        merged.sort(key=lambda item: item.hybrid_score, reverse=True)
        merged = merged[: max(1, int(merged_top_k))]
        return self.reranker.rerank(query, merged, top_k=final_top_k)
