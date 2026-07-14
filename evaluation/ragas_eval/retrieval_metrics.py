from __future__ import annotations

import math
from typing import Any

from evaluation.ragas_eval.config import DEFAULT_K_VALUES


def _unique_ordered(values: list[str]) -> tuple[list[str], int]:
    seen: set[str] = set()
    out: list[str] = []
    duplicate_count = 0
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            duplicate_count += 1
            continue
        seen.add(text)
        out.append(text)
    return out, duplicate_count


def id_context_precision(retrieved_ids: list[str], reference_ids: list[str]) -> float | None:
    retrieved, _ = _unique_ordered(retrieved_ids)
    reference, _ = _unique_ordered(reference_ids)
    if not reference:
        return None
    if not retrieved:
        return 0.0
    return len(set(retrieved) & set(reference)) / len(retrieved)


def id_context_recall(retrieved_ids: list[str], reference_ids: list[str]) -> float | None:
    retrieved, _ = _unique_ordered(retrieved_ids)
    reference, _ = _unique_ordered(reference_ids)
    if not reference:
        return None
    return len(set(retrieved) & set(reference)) / len(reference)


def _ndcg(relevance: list[int], k: int, total_relevant: int) -> float:
    if total_relevant <= 0:
        return 0.0
    top_rel = relevance[:k]
    dcg = sum(rel / math.log2(index + 2) for index, rel in enumerate(top_rel))
    ideal_count = min(total_relevant, k)
    idcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
    return dcg / idcg if idcg > 0 else 0.0


def calculate_retrieval_metrics(
    retrieved_ids: list[str],
    reference_ids: list[str],
    *,
    k_values: list[int] | None = None,
) -> dict[str, Any]:
    k_values = k_values or list(DEFAULT_K_VALUES)
    retrieved, duplicate_count = _unique_ordered(retrieved_ids)
    reference, reference_duplicate_count = _unique_ordered(reference_ids)
    reference_set = set(reference)
    metrics: dict[str, Any] = {
        "metric_backend": "custom_deterministic",
        "retrieved_context_count": len(retrieved),
        "reference_context_count": len(reference),
        "retrieved_duplicate_count": duplicate_count,
        "reference_duplicate_count": reference_duplicate_count,
        "id_context_precision": id_context_precision(retrieved, reference),
        "id_context_recall": id_context_recall(retrieved, reference),
    }

    if not reference:
        for k in k_values:
            metrics[f"recall_at_{k}"] = None
            metrics[f"precision_at_{k}"] = None
            metrics[f"hit_rate_at_{k}"] = None
            metrics[f"ndcg_at_{k}"] = None
        metrics["mrr"] = None
        return metrics

    relevance = [1 if item in reference_set else 0 for item in retrieved]
    first_relevant_rank = next((index + 1 for index, rel in enumerate(relevance) if rel), None)
    metrics["mrr"] = 1.0 / first_relevant_rank if first_relevant_rank else 0.0

    for k in k_values:
        top = retrieved[:k]
        top_hits = len(set(top) & reference_set)
        denominator = len(top)
        metrics[f"recall_at_{k}"] = top_hits / len(reference) if reference else None
        metrics[f"precision_at_{k}"] = top_hits / denominator if denominator else 0.0
        metrics[f"hit_rate_at_{k}"] = 1.0 if top_hits > 0 else 0.0
        metrics[f"ndcg_at_{k}"] = _ndcg(relevance, k, len(reference))
    return metrics
