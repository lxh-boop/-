from __future__ import annotations

import os

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

import config as rag_config
from rag_store import load_rag_documents, refresh_rag_documents
from rag_utils import clean_text

RAG_INDEX_PATH = getattr(
    rag_config,
    "RAG_INDEX_PATH",
    os.path.join("data", "rag_tfidf_index.pkl"),
)
RAG_DOCUMENTS_PATH = getattr(
    rag_config,
    "RAG_DOCUMENTS_PATH",
    os.path.join("data", "rag_documents.csv"),
)
NEWS_CACHE_PATH = getattr(rag_config, "NEWS_CACHE_PATH", os.path.join("data", "news_cache.csv"))
ANNOUNCEMENT_CACHE_PATH = getattr(
    rag_config,
    "ANNOUNCEMENT_CACHE_PATH",
    os.path.join("data", "announcement_cache.csv"),
)


def _document_text(documents: pd.DataFrame) -> list[str]:
    return (
        documents["title"].fillna("").map(clean_text)
        + " "
        + documents["content"].fillna("").map(clean_text)
    ).tolist()


def build_tfidf_index(documents: pd.DataFrame | None = None) -> dict:
    if documents is None:
        documents = load_rag_documents()

    if documents is None or documents.empty:
        return {
            "documents": pd.DataFrame(),
            "vectorizer": None,
            "matrix": None,
            "doc_count": 0,
        }

    documents = documents.reset_index(drop=True).copy()
    texts = _document_text(documents)

    vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(2, 4),
        min_df=1,
        max_features=20000,
    )
    matrix = vectorizer.fit_transform(texts)

    return {
        "documents": documents,
        "vectorizer": vectorizer,
        "matrix": matrix,
        "doc_count": int(len(documents)),
    }


def save_tfidf_index(index: dict, path: str = RAG_INDEX_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    joblib.dump(index, path)


def load_tfidf_index(path: str = RAG_INDEX_PATH) -> dict | None:
    if not os.path.exists(path):
        return None

    try:
        return joblib.load(path)
    except Exception:
        return None


def _mtime(path: str) -> float:
    return os.path.getmtime(path) if os.path.exists(path) else 0.0


def is_index_stale(path: str = RAG_INDEX_PATH) -> bool:
    if not os.path.exists(path):
        return True

    index_time = _mtime(path)
    source_time = max(
        _mtime(RAG_DOCUMENTS_PATH),
        _mtime(NEWS_CACHE_PATH),
        _mtime(ANNOUNCEMENT_CACHE_PATH),
    )

    return source_time > index_time


def ensure_tfidf_index(force_rebuild: bool = False) -> dict:
    if not force_rebuild and not is_index_stale():
        index = load_tfidf_index()
        if index and index.get("doc_count", 0) > 0:
            return index

    documents = refresh_rag_documents()
    index = build_tfidf_index(documents)
    save_tfidf_index(index)
    return index


def rebuild_rag_index() -> dict:
    return ensure_tfidf_index(force_rebuild=True)
