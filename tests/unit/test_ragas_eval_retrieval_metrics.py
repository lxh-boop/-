from __future__ import annotations

import math

from evaluation.ragas_eval.retrieval_metrics import calculate_retrieval_metrics


def test_retrieval_metrics_are_human_checkable() -> None:
    metrics = calculate_retrieval_metrics(
        ["a", "b", "c", "d"],
        ["b", "d", "e"],
        k_values=[1, 3, 5],
    )

    assert metrics["id_context_precision"] == 0.5
    assert metrics["id_context_recall"] == 2 / 3
    assert metrics["recall_at_1"] == 0.0
    assert metrics["precision_at_1"] == 0.0
    assert metrics["hit_rate_at_1"] == 0.0
    assert metrics["recall_at_3"] == 1 / 3
    assert metrics["precision_at_3"] == 1 / 3
    assert metrics["hit_rate_at_3"] == 1.0
    assert metrics["mrr"] == 0.5

    dcg_at_3 = 1 / math.log2(3)
    idcg_at_3 = 1 + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics["ndcg_at_3"] == dcg_at_3 / idcg_at_3


def test_retrieval_metrics_handle_duplicates_and_missing_reference() -> None:
    metrics = calculate_retrieval_metrics(["a", "a", "b"], [], k_values=[1, 3])

    assert metrics["retrieved_context_count"] == 2
    assert metrics["retrieved_duplicate_count"] == 1
    assert metrics["id_context_precision"] is None
    assert metrics["recall_at_3"] is None
    assert metrics["mrr"] is None


def test_precision_denominator_uses_actual_returned_count_when_k_is_large() -> None:
    metrics = calculate_retrieval_metrics(["a", "b"], ["b"], k_values=[50])

    assert metrics["precision_at_50"] == 0.5
    assert metrics["recall_at_50"] == 1.0
    assert metrics["hit_rate_at_50"] == 1.0
