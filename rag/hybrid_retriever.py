from __future__ import annotations

from typing import Any

from rag.bm25_retriever import (
    DEFAULT_BM25_MIN_SIMILARITY,
    DEFAULT_RECALL_CANDIDATE_LIMIT as DEFAULT_BM25_CANDIDATE_LIMIT,
    BM25Retriever,
)
from rag.dense_retriever import (
    DEFAULT_DENSE_MIN_SIMILARITY,
    DEFAULT_RECALL_CANDIDATE_LIMIT as DEFAULT_DENSE_CANDIDATE_LIMIT,
    DenseRetriever,
)
from rag.reranker import DEFAULT_FINAL_RERANK_RESULTS, Reranker
from rag.schemas import RagChunk, RetrievalResult


DEFAULT_RERANK_CANDIDATES = 40
DEFAULT_RECALL_CANDIDATE_LIMIT = min(
    DEFAULT_BM25_CANDIDATE_LIMIT,
    DEFAULT_DENSE_CANDIDATE_LIMIT,
)


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
        self.last_diagnostics: dict[str, Any] = {}

    def build_index(self, chunks: list[RagChunk | dict[str, Any]]) -> "HybridRetriever":
        self.bm25.build_index(chunks)
        self.dense.build_index(chunks)
        return self

    def search(
        self,
        query: str,
        bm25_top_k: int | None = None,
        dense_top_k: int | None = None,
        merged_top_k: int = DEFAULT_RERANK_CANDIDATES,
        final_top_k: int = DEFAULT_FINAL_RERANK_RESULTS,
        metadata_filter: dict[str, Any] | None = None,
        *,
        bm25_min_similarity: float = DEFAULT_BM25_MIN_SIMILARITY,
        dense_min_similarity: float = DEFAULT_DENSE_MIN_SIMILARITY,
        recall_candidate_limit: int = DEFAULT_RECALL_CANDIDATE_LIMIT,
    ) -> list[RetrievalResult]:
        """Threshold-recall with RRF fusion and a maximum of five reranked rows.

        ``bm25_top_k`` and ``dense_top_k`` remain accepted for call-site
        compatibility but are deliberately not used as recall criteria.  Both
        retrieval branches first filter by similarity; ``recall_candidate_limit``
        is only an operational memory bound after thresholding.
        """

        del bm25_top_k, dense_top_k
        candidate_limit = max(1, int(recall_candidate_limit))
        bm25_results = self.bm25.search(
            query,
            top_k=None,
            metadata_filter=metadata_filter,
            min_similarity=float(bm25_min_similarity),
            max_candidates=candidate_limit,
        )
        dense_results = self.dense.search(
            query,
            top_k=None,
            metadata_filter=metadata_filter,
            min_similarity=float(dense_min_similarity),
            max_candidates=candidate_limit,
        )

        by_id: dict[str, dict[str, Any]] = {}

        for rank, item in enumerate(bm25_results, start=1):
            row = by_id.setdefault(item.chunk_id, item.to_dict())
            row["bm25_score"] = item.bm25_score
            row["metadata"] = {**dict(row.get("metadata") or {}), **dict(item.metadata or {})}
            row["_rrf_score"] = float(row.get("_rrf_score", 0.0)) + 1.0 / (self.rrf_k + rank)

        for rank, item in enumerate(dense_results, start=1):
            row = by_id.setdefault(item.chunk_id, item.to_dict())
            row["dense_score"] = item.dense_score
            row["metadata"] = {**dict(row.get("metadata") or {}), **dict(item.metadata or {})}
            row["_rrf_score"] = float(row.get("_rrf_score", 0.0)) + 1.0 / (self.rrf_k + rank)

        merged: list[RetrievalResult] = []
        for row in by_id.values():
            row["hybrid_score"] = float(row.pop("_rrf_score", 0.0))
            merged.append(RetrievalResult(**row))

        merged.sort(key=lambda item: item.hybrid_score, reverse=True)
        merged_limit = max(1, int(merged_top_k))
        merged = merged[:merged_limit]
        final_limit = min(
            DEFAULT_FINAL_RERANK_RESULTS,
            max(1, int(final_top_k or DEFAULT_FINAL_RERANK_RESULTS)),
        )
        results = self.reranker.rerank(query, merged, top_k=final_limit)
        self.last_diagnostics = {
            "recall_policy": "similarity_threshold",
            "bm25_min_similarity": float(bm25_min_similarity),
            "dense_min_similarity": float(dense_min_similarity),
            "recall_candidate_limit": candidate_limit,
            "bm25_recalled_count": len(bm25_results),
            "dense_recalled_count": len(dense_results),
            "merged_candidate_count": len(merged),
            "final_rerank_limit": DEFAULT_FINAL_RERANK_RESULTS,
            "final_result_count": len(results),
        }
        return results
