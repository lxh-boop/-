from __future__ import annotations

from typing import Any

from rag.schemas import RetrievalResult


DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
DEFAULT_RERANKER_MAX_LENGTH = 256


class Reranker:
    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        *,
        max_length: int = DEFAULT_RERANKER_MAX_LENGTH,
    ):
        self.model_name = model_name
        self.max_length = max(64, int(max_length))
        self.model = None
        self.available = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            from sentence_transformers import CrossEncoder

            self.model = CrossEncoder(self.model_name, max_length=self.max_length)
            self.available = True
        except Exception:
            self.model = None
            self.available = False

    def rerank(
        self,
        query: str,
        candidate_chunks: list[RetrievalResult | dict[str, Any]],
        top_k: int = 10,
    ) -> list[RetrievalResult]:
        candidates = [
            item
            if isinstance(item, RetrievalResult)
            else RetrievalResult(
                chunk_id=item["chunk_id"],
                news_id=item.get("news_id", ""),
                chunk_text=item.get("chunk_text", ""),
                bm25_score=float(item.get("bm25_score", 0.0) or 0.0),
                dense_score=float(item.get("dense_score", 0.0) or 0.0),
                hybrid_score=float(item.get("hybrid_score", 0.0) or 0.0),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in candidate_chunks
        ]
        if not candidates:
            return []

        if self.available and self.model is not None:
            pairs = [(query, item.chunk_text) for item in candidates]
            scores = self.model.predict(pairs)
            rows = [
                RetrievalResult(
                    **{
                        **item.to_dict(),
                        "rerank_score": float(score),
                    }
                )
                for item, score in zip(candidates, scores)
            ]
            rows.sort(key=lambda item: item.rerank_score, reverse=True)
        else:
            rows = sorted(candidates, key=lambda item: item.hybrid_score, reverse=True)
            rows = [
                RetrievalResult(
                    **{
                        **item.to_dict(),
                        "rerank_score": float(item.hybrid_score),
                    }
                )
                for item in rows
            ]

        ranked = []
        seen_documents: set[str] = set()
        for item in rows:
            metadata = dict(item.metadata or {})
            document_key = str(
                metadata.get("event_id")
                or metadata.get("document_id")
                or item.news_id
                or item.chunk_id
            )
            if document_key in seen_documents:
                continue
            seen_documents.add(document_key)
            ranked.append(
                RetrievalResult(
                    **{
                        **item.to_dict(),
                        "metadata": {
                            **metadata,
                            "graph_evidence_key": str(
                                metadata.get("graph_evidence_key")
                                or metadata.get("event_id")
                                or metadata.get("document_id")
                                or item.news_id
                                or item.chunk_id
                            ),
                        },
                        "final_rank": len(ranked) + 1,
                    }
                )
            )
            if len(ranked) >= max(1, int(top_k)):
                break
        return ranked
