"""RAG retrieval foundation.

RAG retrieves evidence only. It does not generate investment actions.
"""

from rag.chunkers import (
    build_sentence_chunks,
    chunk_agent_rule,
    chunk_announcement,
    chunk_decision_log,
    chunk_industry_rule,
    chunk_news,
    split_chinese_sentences,
)
from rag.hybrid_retriever import HybridRetriever
from rag.metadata_filter import metadata_matches
from rag.schemas import RagChunk, RetrievalFilters, RetrievalResult

__all__ = [
    "RagChunk",
    "RetrievalFilters",
    "RetrievalResult",
    "HybridRetriever",
    "metadata_matches",
    "split_chinese_sentences",
    "build_sentence_chunks",
    "chunk_news",
    "chunk_announcement",
    "chunk_decision_log",
    "chunk_industry_rule",
    "chunk_agent_rule",
]
