from __future__ import annotations

from database.repositories import NewsRepository
from rag.retrieval_logger import RetrievalLogger


def test_retrieval_logger_writes_db_and_updates_chunk(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    news_repo = NewsRepository(db_path)
    news_repo.insert_news_chunk(
        {
            "chunk_id": "chunk_001",
            "news_id": "news_001",
            "chunk_index": 0,
            "chunk_text": "公司回购公告。",
            "trade_date": "2026-06-11",
            "retrieval_count": 0,
        }
    )
    logger = RetrievalLogger(db_path)

    retrieval_id = logger.log_retrieval(
        query="回购",
        query_type="recommendation_explanation",
        trade_date="2026-06-11",
        decision_time="2026-06-11 14:00:00",
        filters={"stock_code": "000001"},
        bm25_results=[{"chunk_id": "chunk_001", "score": 1.0}],
        dense_results=[],
        rerank_results=[{"chunk_id": "chunk_001", "score": 1.0}],
        returned_chunk_ids=["chunk_001"],
        bm25_top_k=50,
        dense_top_k=0,
        rerank_top_k=10,
    )

    row = news_repo.get_rag_retrieval_log(retrieval_id)
    chunk = news_repo.get_news_chunk("chunk_001")
    assert row["returned_chunk_ids"] == ["chunk_001"]
    assert row["filters"] == {"stock_code": "000001"}
    assert chunk["retrieval_count"] == 1

    logger.mark_used_by_agent(retrieval_id, "decision_001", ["chunk_001"])
    used_chunk = news_repo.get_news_chunk("chunk_001")
    used_row = news_repo.get_rag_retrieval_log(retrieval_id)
    assert used_chunk["used_in_decision"] == 1
    assert used_chunk["decision_id"] == "decision_001"
    assert used_row["used_chunk_ids"] == ["chunk_001"]
