from __future__ import annotations

import threading
import time

from database.repositories import NewsRepository
from pipelines.rag_pipeline import run_rag_pipeline
from pipelines.schemas import PipelineContext, PipelineStatus
from rag.schemas import RetrievalResult
from scoring.schemas import ModelPredictionSignal


def test_rag_pipeline_no_news_returns_empty_evidence_and_logs(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", decision_time="2026-06-11 14:30:00", db_path=tmp_path / "agent_quant.db")
    prediction = ModelPredictionSignal("2026-06-11", "000001", 0.9, stock_name="Demo")

    result = run_rag_pipeline(context, [prediction], chunks=[])

    assert result.status == PipelineStatus.SUCCESS
    assert result.evidence == []
    assert len(result.retrieval_ids) == 1
    assert NewsRepository(tmp_path / "agent_quant.db").get_rag_retrieval_log(result.retrieval_ids[0]) is not None


def test_rag_pipeline_returns_evidence_from_chunks(tmp_path) -> None:
    context = PipelineContext(user_id="u1", trade_date="2026-06-11", decision_time="2026-06-11 14:30:00", db_path=tmp_path / "agent_quant.db")
    prediction = ModelPredictionSignal("2026-06-11", "000001", 0.9, stock_name="Demo")
    chunks = [
        {
            "chunk_id": "chunk_001",
            "news_id": "news_001",
            "chunk_index": 0,
            "chunk_text": "Demo company faces regulatory risk event",
            "stock_code": "000001",
            "trade_date": "2026-06-11",
            "publish_time": "2026-06-11 10:00:00",
            "metadata": {"mapping_confidence": 0.9, "impact_direction": "negative", "impact_strength": 0.8},
        }
    ]

    result = run_rag_pipeline(context, [prediction], chunks=chunks)

    assert result.status == PipelineStatus.SUCCESS
    assert result.evidence
    assert result.evidence[0].news_id == "news_001"


class _ConcurrentFakeRetriever:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def build_index(self, chunks):
        _ = chunks
        return self

    def search(self, query, final_top_k=3, metadata_filter=None):
        _ = final_top_k
        code = (metadata_filter or {}).get("stock_code", "")
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return [
                RetrievalResult(
                    chunk_id=f"chunk_{code}",
                    news_id=f"news_{code}",
                    chunk_text=f"{query} risk event",
                    metadata={
                        "stock_code": code,
                        "trade_date": (metadata_filter or {}).get("trade_date_end", ""),
                    },
                )
            ]
        finally:
            with self.lock:
                self.active -= 1


def test_rag_pipeline_runs_stock_searches_in_parallel(tmp_path) -> None:
    context = PipelineContext(
        user_id="u1",
        trade_date="2026-06-11",
        decision_time="2026-06-11 14:30:00",
        db_path=tmp_path / "agent_quant.db",
    )
    predictions = [
        ModelPredictionSignal("2026-06-11", f"{index:06d}", 0.9, stock_name=f"Demo{index}")
        for index in range(1, 5)
    ]
    retriever = _ConcurrentFakeRetriever()

    result = run_rag_pipeline(
        context,
        predictions,
        chunks=[],
        retriever=retriever,
        max_workers=4,
    )

    assert result.status == PipelineStatus.SUCCESS
    assert retriever.max_active > 1
    assert len(result.evidence) == len(predictions)
    assert len(result.retrieval_ids) == len(predictions)
