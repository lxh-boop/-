from __future__ import annotations

import math

import numpy as np

from core.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from core.llm.profiles import ModelProfile
from rag.bm25_retriever import BM25Retriever
from rag.dense_retriever import DenseRetriever
from rag.reranker import DEFAULT_FINAL_RERANK_RESULTS, Reranker
from rag.schemas import RagChunk, RetrievalResult


def _profile(*, deployment_mode: str = "api") -> ModelProfile:
    return ModelProfile(
        profile_id=f"{deployment_mode}:qwen:test",
        provider_id="openai_compatible",
        deployment_mode=deployment_mode,
        model_name="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        credential_ref="runtime:test",
        disable_thinking=False,
        request_timeout_seconds=120,
        max_retries=0,
        context_window=128000,
        supports_json_schema=True,
        supports_tools=True,
    )


def test_qwen_api_uses_official_enable_thinking_parameter() -> None:
    profile = _profile()
    messages = [{"role": "system", "content": "system"}]

    assert OpenAICompatibleAdapter._prepared_messages(
        profile, messages, disable_thinking=True
    ) == messages
    assert OpenAICompatibleAdapter._provider_parameters(
        profile, disable_thinking=True
    ) == {"extra_body": {"enable_thinking": False}}
    assert OpenAICompatibleAdapter._provider_parameters(
        profile, disable_thinking=False
    ) == {"extra_body": {"enable_thinking": True}}


def test_non_api_qwen_keeps_no_think_compatibility_marker() -> None:
    profile = _profile(deployment_mode="local")
    messages = [{"role": "system", "content": "system"}]

    prepared = OpenAICompatibleAdapter._prepared_messages(
        profile, messages, disable_thinking=True
    )

    assert prepared[0]["content"].endswith("/no_think")
    assert messages[0]["content"] == "system"


def test_bm25_recall_uses_similarity_threshold_before_compatibility_cap() -> None:
    chunks = [
        RagChunk("c1", "n1", 0, "回购 增持 回购 增持", stock_codes=["600519"]),
        RagChunk("c2", "n2", 0, "回购 普通公告", stock_codes=["600519"]),
        RagChunk("c3", "n3", 0, "天气晴朗", stock_codes=["600519"]),
    ]
    retriever = BM25Retriever(financial_terms=["回购", "增持"]).build_index(chunks)

    results = retriever.search(
        "回购 增持",
        top_k=None,
        min_similarity=0.80,
        max_candidates=200,
    )

    assert [item.chunk_id for item in results] == ["c1"]
    assert results[0].metadata["bm25_similarity"] == 1.0
    assert results[0].metadata["bm25_similarity_threshold"] == 0.80


def test_dense_recall_uses_cosine_similarity_threshold(monkeypatch) -> None:
    monkeypatch.setattr(DenseRetriever, "_load_model", lambda self: None)
    retriever = DenseRetriever(model_name="fake")
    retriever.available = True
    retriever.chunks = [
        RagChunk("c1", "n1", 0, "high", stock_codes=["600519"]),
        RagChunk("c2", "n2", 0, "low", stock_codes=["600519"]),
        RagChunk("c3", "n3", 0, "opposite", stock_codes=["600519"]),
    ]
    retriever.embeddings = np.asarray(
        [
            [1.0, 0.0],
            [0.30, math.sqrt(1.0 - 0.30**2)],
            [0.0, 1.0],
        ],
        dtype=float,
    )
    retriever.embedding_dimension = 2
    monkeypatch.setattr(
        retriever,
        "embed_texts",
        lambda _texts: np.asarray([[1.0, 0.0]], dtype=float),
    )

    results = retriever.search(
        "query",
        top_k=None,
        min_similarity=0.35,
        max_candidates=200,
    )

    assert [item.chunk_id for item in results] == ["c1"]
    assert results[0].metadata["dense_similarity"] == 1.0
    assert results[0].metadata["dense_similarity_threshold"] == 0.35


def test_reranker_never_returns_more_than_five_documents() -> None:
    reranker = Reranker()
    reranker.available = False
    candidates = [
        RetrievalResult(
            chunk_id=f"chunk_{index}",
            news_id=f"news_{index}",
            chunk_text=f"document {index}",
            hybrid_score=float(100 - index),
        )
        for index in range(12)
    ]

    results = reranker.rerank("query", candidates, top_k=50)

    assert len(results) == DEFAULT_FINAL_RERANK_RESULTS == 5
    assert [item.final_rank for item in results] == [1, 2, 3, 4, 5]
