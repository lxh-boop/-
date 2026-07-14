from __future__ import annotations

import pickle
import hashlib
from pathlib import Path
from typing import Any

import numpy as np

from rag.metadata_filter import filter_chunks
from rag.schemas import RagChunk, RetrievalResult


DEFAULT_DENSE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DENSE_INDEX_SCHEMA_VERSION = 1


class DenseRetriever:
    def __init__(self, model_name: str = DEFAULT_DENSE_MODEL):
        self.model_name = model_name
        self.embedding_model_name = model_name
        self.model = None
        self.available = False
        self.embedding_dimension = 0
        self.index_version = ""
        self.load_error = ""
        self.fallback_reason = ""
        self.chunks: list[RagChunk] = []
        self.embeddings: np.ndarray | None = None
        self._load_model()

    def _load_model(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name)
            self.available = True
            self.load_error = ""
            self.fallback_reason = ""
        except Exception as exc:
            self.model = None
            self.available = False
            self.load_error = f"{type(exc).__name__}: {exc}"
            self.fallback_reason = "Dense retrieval disabled because sentence-transformers model loading failed."

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not self.available or self.model is None:
            return np.empty((len(texts), 0), dtype=float)
        try:
            embeddings = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        except Exception as exc:
            self.available = False
            self.load_error = f"{type(exc).__name__}: {exc}"
            self.fallback_reason = "Dense retrieval disabled because embedding generation failed."
            return np.empty((len(texts), 0), dtype=float)
        data = np.asarray(embeddings, dtype=float)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        self.embedding_dimension = int(data.shape[1]) if data.ndim == 2 and data.size else 0
        return data

    def _set_index_version(self) -> None:
        chunk_hash = hashlib.sha1(
            "\n".join(chunk.chunk_id for chunk in self.chunks).encode("utf-8")
        ).hexdigest()[:12]
        self.index_version = (
            f"dense-v{DENSE_INDEX_SCHEMA_VERSION}:"
            f"{self.embedding_model_name}:"
            f"dim{self.embedding_dimension}:"
            f"chunks{len(self.chunks)}:"
            f"{chunk_hash}"
        )

    def build_index(self, chunks: list[RagChunk | dict[str, Any]]) -> "DenseRetriever":
        self.chunks = [chunk if isinstance(chunk, RagChunk) else RagChunk.from_mapping(chunk) for chunk in chunks]
        if self.available:
            self.embeddings = self.embed_texts([chunk.chunk_text for chunk in self.chunks])
        else:
            self.embeddings = np.empty((len(self.chunks), 0), dtype=float)
            self.embedding_dimension = 0
        self._set_index_version()
        return self

    def search(
        self,
        query: str,
        top_k: int = 10,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        if not self.available or self.embeddings is None or self.embeddings.shape[1] == 0:
            return []
        query_embedding = self.embed_texts([query])
        if query_embedding.shape[1] == 0:
            return []
        scores = np.dot(self.embeddings, query_embedding[0])
        allowed = {chunk.chunk_id for chunk in filter_chunks(self.chunks, metadata_filter)}
        rows = []
        for chunk, score in zip(self.chunks, scores):
            if chunk.chunk_id not in allowed:
                continue
            rows.append(
                RetrievalResult(
                    chunk_id=chunk.chunk_id,
                    news_id=chunk.news_id,
                    chunk_text=chunk.chunk_text,
                    dense_score=float(score),
                    metadata=chunk.to_dict(),
                )
            )
        rows.sort(key=lambda item: item.dense_score, reverse=True)
        return rows[: max(1, int(top_k))]

    def save_index(self, path: str | Path) -> Path:
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": DENSE_INDEX_SCHEMA_VERSION,
            "model_name": self.model_name,
            "embedding_model_name": self.embedding_model_name,
            "embedding_dimension": self.embedding_dimension,
            "index_version": self.index_version,
            "available": self.available,
            "load_error": self.load_error,
            "fallback_reason": self.fallback_reason,
            "chunks": self.chunks,
            "embeddings": self.embeddings,
        }
        with out_path.open("wb") as f:
            pickle.dump(payload, f)
        return out_path

    def status(self) -> dict[str, Any]:
        return {
            "available": bool(self.available),
            "embedding_model_name": self.embedding_model_name,
            "embedding_dimension": int(self.embedding_dimension or 0),
            "index_version": self.index_version,
            "schema_version": DENSE_INDEX_SCHEMA_VERSION,
            "load_error": self.load_error,
            "fallback_reason": self.fallback_reason,
            "chunk_count": len(self.chunks),
        }

    @classmethod
    def load_index(cls, path: str | Path) -> "DenseRetriever":
        with Path(path).open("rb") as f:
            payload = pickle.load(f)
        obj = cls(model_name=payload.get("model_name") or DEFAULT_DENSE_MODEL)
        payload_available = bool(payload.get("available"))
        current_available = bool(obj.available)
        obj.available = payload_available and current_available
        obj.embedding_model_name = payload.get("embedding_model_name") or obj.model_name
        obj.embedding_dimension = int(payload.get("embedding_dimension") or 0)
        obj.index_version = str(payload.get("index_version") or "")
        obj.load_error = str(payload.get("load_error") or obj.load_error or "")
        obj.fallback_reason = str(payload.get("fallback_reason") or obj.fallback_reason or "")
        if payload_available and not current_available and not obj.fallback_reason:
            obj.fallback_reason = "Dense index exists but local embedding model is unavailable."
        obj.chunks = payload.get("chunks") or []
        obj.embeddings = payload.get("embeddings")
        return obj
