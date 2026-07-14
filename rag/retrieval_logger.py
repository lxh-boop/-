from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from database.repositories import NewsRepository
from rag.utils import stable_id


class RetrievalLogger:
    def __init__(self, db_path: str | Path | None = None):
        self.news_repo = NewsRepository(db_path)

    def log_retrieval(
        self,
        query: str,
        query_type: str,
        trade_date: str,
        decision_time: str,
        filters: dict[str, Any] | None,
        bm25_results: list[dict[str, Any]],
        dense_results: list[dict[str, Any]],
        rerank_results: list[dict[str, Any]],
        returned_chunk_ids: list[str],
        used_chunk_ids: list[str] | None = None,
        bm25_top_k: int = 50,
        dense_top_k: int = 50,
        rerank_top_k: int = 10,
        retrieval_id: str | None = None,
        user_id: str = "",
        stock_code: str = "",
    ) -> str:
        retrieval_id = retrieval_id or stable_id(query, query_type, decision_time, prefix="retrieval_")
        used_chunk_ids = used_chunk_ids or []
        self.news_repo.insert_rag_retrieval_log(
            {
                "retrieval_id": retrieval_id,
                "query": query,
                "query_type": query_type,
                "user_id": user_id,
                "stock_code": stock_code,
                "trade_date": trade_date,
                "decision_time": decision_time,
                "filters": filters or {},
                "bm25_results": bm25_results,
                "dense_results": dense_results,
                "rerank_results": rerank_results,
                "selected_chunk_ids": returned_chunk_ids,
                "returned_chunk_ids": returned_chunk_ids,
                "used_chunk_ids": used_chunk_ids,
                "bm25_top_k": int(bm25_top_k),
                "dense_top_k": int(dense_top_k),
                "rerank_top_k": int(rerank_top_k),
                "created_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        for chunk_id in returned_chunk_ids:
            self.news_repo.increment_chunk_retrieval_count(chunk_id)
        return retrieval_id

    def mark_used_by_agent(self, retrieval_id: str, decision_id: str, used_chunk_ids: list[str]) -> None:
        for chunk_id in used_chunk_ids:
            self.news_repo.mark_chunk_used_in_decision(chunk_id, decision_id)
        row = self.news_repo.get_rag_retrieval_log(retrieval_id)
        if row:
            current_used = list(dict.fromkeys((row.get("used_chunk_ids") or []) + used_chunk_ids))
            self.news_repo.insert_rag_retrieval_log({**row, "used_chunk_ids": current_used})
