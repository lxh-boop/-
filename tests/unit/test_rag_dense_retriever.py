from __future__ import annotations

import numpy as np

from rag.dense_retriever import DenseRetriever
from rag.schemas import RagChunk


class _FakeModel:
    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        rows = []
        for index, _text in enumerate(texts):
            rows.append([1.0, float(index + 1), 0.5])
        return np.asarray(rows, dtype=float)


def test_dense_retriever_records_explicit_fallback_when_model_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(DenseRetriever, "_load_model", lambda self: None)
    dense = DenseRetriever(model_name="missing-test-model")
    dense.available = False
    dense.load_error = "ModuleNotFoundError: No module named sentence_transformers"
    dense.fallback_reason = "Dense retrieval disabled in unit test."
    dense.build_index([RagChunk("c1", "n1", 0, "profit growth", stock_codes=["000001"])])

    status = dense.status()

    assert status["available"] is False
    assert status["embedding_dimension"] == 0
    assert status["embedding_model_name"] == "missing-test-model"
    assert status["index_version"].startswith("dense-v1:missing-test-model:dim0:chunks1:")
    assert "Dense retrieval disabled" in status["fallback_reason"]


def test_dense_retriever_records_dimension_and_index_version_when_available(monkeypatch) -> None:
    monkeypatch.setattr(DenseRetriever, "_load_model", lambda self: None)
    dense = DenseRetriever(model_name="fake-multilingual-embedding")
    dense.model = _FakeModel()
    dense.available = True

    dense.build_index(
        [
            RagChunk("c1", "n1", 0, "Ping An Bank profit growth", stock_codes=["000001"]),
            RagChunk("c2", "n2", 0, "credit risk disclosure", stock_codes=["000001"]),
        ]
    )

    results = dense.search("profit", top_k=1, metadata_filter={"stock_code": "000001"})
    status = dense.status()

    assert results
    assert status["available"] is True
    assert status["embedding_dimension"] == 3
    assert status["index_version"].startswith("dense-v1:fake-multilingual-embedding:dim3:chunks2:")
