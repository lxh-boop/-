from __future__ import annotations

import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity

from rag_indexer import ensure_tfidf_index, rebuild_rag_index
from rag_utils import normalize_code, normalize_query

RESULT_COLUMNS = [
    "date",
    "title",
    "source",
    "url",
    "score",
    "content",
]


def retrieve_stock_context(
    code: str,
    query: str,
    top_k: int = 5,
    force_rebuild: bool = False,
) -> pd.DataFrame:
    code = normalize_code(code)
    query = normalize_query(query)
    top_k = max(1, int(top_k))

    index = rebuild_rag_index() if force_rebuild else ensure_tfidf_index()
    docs = index.get("documents")
    vectorizer = index.get("vectorizer")
    matrix = index.get("matrix")

    if docs is None or docs.empty or vectorizer is None or matrix is None:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    stock_docs = docs[docs["code"].astype(str).str.zfill(6) == code].copy()

    if stock_docs.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    stock_positions = stock_docs.index.to_numpy()
    query_vec = vectorizer.transform([query])
    scores = cosine_similarity(query_vec, matrix[stock_positions]).ravel()

    result = stock_docs.copy()
    result["score"] = scores
    result = result.sort_values(["score", "date"], ascending=[False, False]).head(top_k)

    out = result[[c for c in RESULT_COLUMNS if c in result.columns]].copy()

    for col in RESULT_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    out["score"] = pd.to_numeric(out["score"], errors="coerce").fillna(0.0)
    return out[RESULT_COLUMNS].reset_index(drop=True)


if __name__ == "__main__":
    sample = retrieve_stock_context("600519", "近期有什么风险", top_k=5, force_rebuild=True)
    print(sample.to_string(index=False))
