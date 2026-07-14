from __future__ import annotations

from pathlib import Path
from typing import Any

from database.repositories import NewsRepository
from scoring.schemas import COMPLIANCE_DISCLAIMER


def search_evidence(
    query: str,
    filters: dict[str, Any] | None = None,
    db_path: str | Path | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    filters = filters or {}
    try:
        repo = NewsRepository(db_path)
        rows = repo.list_news_chunks(
            stock_code=filters.get("stock_code"),
            trade_date=filters.get("trade_date"),
        )
        query_text = str(query or "").lower()
        if query_text:
            matched = [
                row
                for row in rows
                if query_text in str(row.get("chunk_text") or "").lower()
                or query_text in str(row.get("event_type") or "").lower()
                or query_text in str(row.get("industry") or "").lower()
            ]
        else:
            matched = rows
        evidence = [
            {
                "chunk_id": row.get("chunk_id"),
                "news_id": row.get("news_id"),
                "chunk_text": row.get("chunk_text"),
                "stock_code": row.get("stock_code"),
                "industry": row.get("industry"),
                "event_type": row.get("event_type"),
                "trade_date": row.get("trade_date"),
                "source": row.get("source"),
            }
            for row in matched[: int(top_k)]
        ]
        return {
            "ok": bool(evidence),
            "evidence": evidence,
            "count": len(evidence),
            "message": "evidence found" if evidence else "no evidence found",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
            "note": "RAG evidence is context only and cannot create buy or sell decisions.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "evidence": [],
            "count": 0,
            "message": f"failed to search evidence: {exc}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }


def get_news_chunks(
    chunk_ids: list[str],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        repo = NewsRepository(db_path)
        chunks = []
        missing = []
        for chunk_id in chunk_ids:
            row = repo.get_news_chunk(str(chunk_id))
            if row:
                chunks.append(row)
            else:
                missing.append(str(chunk_id))
        return {
            "ok": bool(chunks),
            "chunks": chunks,
            "missing_chunk_ids": missing,
            "count": len(chunks),
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    except Exception as exc:
        return {
            "ok": False,
            "chunks": [],
            "missing_chunk_ids": list(chunk_ids),
            "message": f"failed to load chunks: {exc}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }


def get_retrieval_log(
    retrieval_id: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        row = NewsRepository(db_path).get_rag_retrieval_log(retrieval_id)
        return {
            "ok": bool(row),
            "retrieval_log": row or {},
            "message": "retrieval log loaded" if row else f"retrieval_id={retrieval_id} not found",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
    except Exception as exc:
        return {
            "ok": False,
            "retrieval_log": {},
            "message": f"failed to load retrieval log: {exc}",
            "compliance_disclaimer": COMPLIANCE_DISCLAIMER,
        }
