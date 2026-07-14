from __future__ import annotations

import pandas as pd

from evaluation import news_rag_diagnostics as diag
from news_db_sync import sync_event_cache_to_agent_db


class _FakeDenseRetriever:
    model_name = "fake-dense"

    def __init__(self, *args, **kwargs) -> None:
        self.available = False
        self.chunks = []

    def build_index(self, chunks):
        self.chunks = list(chunks)
        return self

    def search(self, *args, **kwargs):
        return []

    def save_index(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake")
        return path

    def status(self):
        return {
            "available": False,
            "embedding_model_name": self.model_name,
            "embedding_dimension": 0,
            "index_version": "dense-v1:fake-dense:dim0:chunks2:test",
            "schema_version": 1,
            "load_error": "unit-test",
            "fallback_reason": "unit-test fallback",
            "chunk_count": len(self.chunks),
        }


class _FakeReranker:
    available = False
    model_name = "fake-reranker"

    def rerank(self, query, candidate_chunks, top_k=10):
        rows = []
        for rank, item in enumerate(candidate_chunks[:top_k], start=1):
            rows.append(type(item)(**{**item.to_dict(), "rerank_score": item.hybrid_score, "final_rank": rank}))
        return rows


def test_news_rag_diagnostics_are_diagnostic_only_and_check_filters(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(diag, "DenseRetriever", _FakeDenseRetriever)
    monkeypatch.setattr(diag, "Reranker", _FakeReranker)
    db_path = tmp_path / "agent_quant.db"
    events = pd.DataFrame(
        [
            {
                "date": "2026-06-23",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Ping An Bank profit growth",
                "summary": "Profit improved for Ping An Bank.",
                "content": "Ping An Bank reported profit growth and lower credit risk.",
                "source": "unit_test_news",
                "url": "https://example.test/news/1",
                "publish_time": "2026-06-23 10:00:00",
            },
            {
                "date": "2026-06-24",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Future after decision",
                "summary": "This should be blocked by decision time.",
                "content": "Future information after the decision time.",
                "source": "unit_test_news",
                "url": "https://example.test/news/2",
                "publish_time": "2026-06-24 18:00:00",
            },
        ]
    )
    sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=events)

    report = diag.run_news_rag_diagnostics(
        db_path,
        query="000001 Ping An Bank profit risk",
        stock_code="000001",
        decision_time="2026-06-24 14:30:00",
        output_dir=tmp_path / "outputs",
        rebuild_indexes=False,
    )

    assert report["acceptance_eligible"] is False
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["future_information_leakage"]["passed"] is True
    assert checks["future_information_leakage"]["details"]["future_blocked_count"] >= 1
    assert checks["retrieval_source_traceability"]["passed"] is True
    assert checks["bm25_exact_hit"]["passed"] is True
    assert checks["hybrid_reranker_topk"]["passed"] is True
    assert report["statistics"]["content_level_distribution"] == {"full_text": 2}
    assert report["statistics"]["future_news_filtered_count"] >= 1
    assert checks["dense_semantic_recall"]["details"]["dense_status"]["fallback_reason"] == "unit-test fallback"


def test_news_rag_diagnostics_require_dense_fails_when_dense_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(diag, "DenseRetriever", _FakeDenseRetriever)
    monkeypatch.setattr(diag, "Reranker", _FakeReranker)
    db_path = tmp_path / "agent_quant.db"
    events = pd.DataFrame(
        [
            {
                "date": "2026-06-23",
                "code": "000001",
                "name": "Ping An Bank",
                "title": "Ping An Bank profit growth",
                "summary": "Profit improved for Ping An Bank.",
                "content": "Ping An Bank reported profit growth and lower credit risk.",
                "source": "unit_test_news",
                "url": "https://example.test/news/1",
                "publish_time": "2026-06-23 10:00:00",
            }
        ]
    )
    sync_event_cache_to_agent_db(stock_pool={"000001": "Ping An Bank"}, db_path=db_path, events=events)

    report = diag.run_news_rag_diagnostics(
        db_path,
        query="000001 Ping An Bank profit risk",
        stock_code="000001",
        decision_time="2026-06-24 14:30:00",
        output_dir=tmp_path / "outputs",
        rebuild_indexes=False,
        require_dense=True,
    )

    checks = {item["name"]: item for item in report["checks"]}
    assert checks["dense_semantic_recall"]["passed"] is False
    assert report["summary"]["failed"] == 1
