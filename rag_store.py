from __future__ import annotations

import os

import pandas as pd

import config as rag_config
from news_data import load_event_cache
from rag_utils import clean_text, make_doc_id, normalize_code

RAG_DOCUMENTS_PATH = getattr(
    rag_config,
    "RAG_DOCUMENTS_PATH",
    os.path.join("data", "rag_documents.csv"),
)

DOCUMENT_COLUMNS = [
    "doc_id",
    "code",
    "name",
    "date",
    "title",
    "content",
    "source",
    "url",
]


def build_rag_documents(stock_pool: dict | None = None) -> pd.DataFrame:
    events = load_event_cache(stock_pool=stock_pool)

    if events is None or events.empty:
        return pd.DataFrame(columns=DOCUMENT_COLUMNS)

    data = events.copy()
    data["code"] = data["code"].map(normalize_code)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data = data.dropna(subset=["date", "code"]).copy()

    data["title"] = data.get("title", "").map(clean_text)

    if "content" in data.columns:
        data["content"] = data["content"].map(clean_text)
        data.loc[data["content"] == "", "content"] = data["title"]
    else:
        data["content"] = data["title"]

    if "name" not in data.columns:
        data["name"] = ""
    else:
        data["name"] = data["name"].fillna("").map(clean_text)

    if "source" not in data.columns:
        data["source"] = ""
    else:
        data["source"] = data["source"].fillna("").map(clean_text)

    if "url" not in data.columns:
        data["url"] = ""
    else:
        data["url"] = data["url"].fillna("").map(clean_text)

    data["doc_id"] = data.apply(
        lambda row: make_doc_id(
            row["code"],
            row["date"].strftime("%Y-%m-%d"),
            row["title"],
            row["source"],
        ),
        axis=1,
    )
    data["date"] = data["date"].dt.strftime("%Y-%m-%d")

    docs = data[DOCUMENT_COLUMNS].copy()
    docs = docs.drop_duplicates(subset=["doc_id"], keep="last")
    docs = docs.sort_values(["date", "code", "doc_id"]).reset_index(drop=True)

    return docs


def save_rag_documents(documents: pd.DataFrame, path: str = RAG_DOCUMENTS_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    documents.to_csv(path, index=False, encoding="utf-8-sig")


def load_rag_documents(path: str = RAG_DOCUMENTS_PATH) -> pd.DataFrame:
    if not os.path.exists(path):
        docs = build_rag_documents()
        save_rag_documents(docs, path=path)
        return docs

    try:
        docs = pd.read_csv(path, dtype={"code": str, "doc_id": str})
    except Exception:
        docs = build_rag_documents()
        save_rag_documents(docs, path=path)
        return docs

    if docs.empty:
        return pd.DataFrame(columns=DOCUMENT_COLUMNS)

    for col in DOCUMENT_COLUMNS:
        if col not in docs.columns:
            docs[col] = ""

    docs["code"] = docs["code"].map(normalize_code)
    docs = docs[DOCUMENT_COLUMNS].copy()
    return docs


def refresh_rag_documents(path: str = RAG_DOCUMENTS_PATH) -> pd.DataFrame:
    docs = build_rag_documents()
    save_rag_documents(docs, path=path)
    return docs
