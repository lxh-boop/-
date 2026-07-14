from __future__ import annotations

from evaluation.ragas_eval.ragas_metrics import get_ragas_version, id_metrics_with_optional_ragas, llm_metrics_with_optional_ragas
from evaluation.ragas_eval.config import RagasEvalRuntimeConfig
from evaluation.ragas_eval.schemas import EvaluationCase


def test_ragas_metrics_import_without_ragas_and_no_llm_still_works() -> None:
    metrics = id_metrics_with_optional_ragas(["a", "b"], ["b"])

    assert metrics["id_context_precision"] == 0.5
    assert metrics["id_context_recall"] == 1.0
    assert metrics["id_context_metric_backend"] in {"custom_deterministic", "ragas"}

    case = EvaluationCase.from_mapping({
        "case_id": "case_1",
        "user_input": "查询",
        "stock_code": "000001",
        "decision_time": "2026-06-20T15:00:00+08:00",
        "reference_context_ids": [],
    })
    skipped = llm_metrics_with_optional_ragas(case, [], response="", runtime=RagasEvalRuntimeConfig(), no_llm=True)
    assert skipped["llm_metric_status"] == "skipped"
    assert get_ragas_version()
