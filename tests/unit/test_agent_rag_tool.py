from __future__ import annotations

from agent.rag_tool import get_news_chunks, get_retrieval_log, search_evidence
from database.repositories import NewsRepository


def test_rag_tool_reads_chunks_and_retrieval_log(tmp_path) -> None:
    db_path = tmp_path / "agent_quant.db"
    repo = NewsRepository(db_path)
    repo.insert_news_chunk(
        {
            "chunk_id": "chunk_1",
            "news_id": "news_1",
            "chunk_index": 0,
            "chunk_text": "policy event affects bank earnings",
            "stock_code": "000001",
            "industry": "bank",
            "event_type": "policy",
            "trade_date": "2026-06-11",
        }
    )
    repo.insert_rag_retrieval_log(
        {
            "retrieval_id": "retrieval_1",
            "query": "policy",
            "query_type": "event",
            "trade_date": "2026-06-11",
            "filters": {"stock_code": "000001"},
            "selected_chunk_ids": ["chunk_1"],
            "returned_chunk_ids": ["chunk_1"],
            "used_chunk_ids": [],
        }
    )

    evidence = search_evidence("policy", filters={"stock_code": "000001"}, db_path=db_path)
    assert evidence["ok"] is True
    assert evidence["evidence"][0]["chunk_id"] == "chunk_1"

    chunks = get_news_chunks(["chunk_1"], db_path=db_path)
    assert chunks["chunks"][0]["chunk_text"].startswith("policy")

    log = get_retrieval_log("retrieval_1", db_path=db_path)
    assert log["retrieval_log"]["returned_chunk_ids"] == ["chunk_1"]
