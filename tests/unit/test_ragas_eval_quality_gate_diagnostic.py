from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from evaluation.ragas_eval.config import RagasEvalConfig
from evaluation.ragas_eval.result_exporter import export_results
from evaluation.ragas_eval.schemas import CaseRunResult, EvaluationCase


def test_auto_seed_dataset_is_not_acceptance_eligible(tmp_path) -> None:
    case = EvaluationCase.from_mapping(
        {
            "case_id": "auto_seed_001",
            "user_input": "查询新闻风险",
            "stock_code": "601360",
            "decision_time": "2026-06-24T15:00:00+08:00",
            "reference_context_ids": ["chunk_1"],
            "tags": ["auto_seed"],
            "metadata": {"gold_level": "diagnostic_not_human_gold"},
        }
    )
    result = CaseRunResult(case=case, metrics={"content_faithfulness": 1.0, "future_leak_rate": 0.0})

    _, summary = export_results(
        output_dir=tmp_path / "out",
        config=RagasEvalConfig(),
        results=[result],
        failed_cases=[],
        dataset_errors=[],
        dataset_warnings=[],
        start_time=datetime(2026, 6, 24, tzinfo=ZoneInfo("Asia/Shanghai")),
        end_time=datetime(2026, 6, 24, 0, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    gates = summary["quality_gates"]
    assert gates["acceptance_eligible"] is False
    assert gates["overall_passed"] is None
    assert "diagnostic auto-seed" in gates["reason"]


def test_formal_acceptance_requires_30_captured_and_fully_scored_cases(tmp_path) -> None:
    results = []
    for index in range(30):
        case = EvaluationCase.from_mapping({
            "case_id": f"formal_{index:03d}",
            "user_input": f"查询 002468 的新闻证据 {index}",
            "stock_code": "002468",
            "decision_time": "2026-06-24T15:00:00+08:00",
            "reference": "公司公告了股份回购计划。",
            "reference_context_ids": [f"chunk_{index}"],
            "actual_response": "公司公告了股份回购计划。",
            "response_run_id": f"agent_run_{index}",
            "response_source": "production_agent_runtime",
            "metadata": {
                "gold_level": "manual_reference",
                "reference_content_level": "full_text",
            },
        })
        results.append(CaseRunResult(
            case=case,
            answer_metadata={
                "uses_captured_actual_response": True,
                "normalization_method": "deterministic_boilerplate_removal",
            },
            metrics={
                "context_precision": 0.9,
                "context_recall": 0.9,
                "content_faithfulness": 0.9,
                "response_relevancy": 0.9,
                "answer_relevancy_status": "success",
                "embedding_backend": "local_sentence_transformers",
                "future_leak_rate": 0.0,
                "wrong_stock_rate": 0.0,
                "duplicate_event_rate": 0.0,
                "recall_at_10": 1.0,
            },
        ))

    _, summary = export_results(
        output_dir=tmp_path / "formal",
        config=RagasEvalConfig(),
        results=results,
        failed_cases=[],
        dataset_errors=[],
        dataset_warnings=[],
        start_time=datetime(2026, 6, 24, tzinfo=ZoneInfo("Asia/Shanghai")),
        end_time=datetime(2026, 6, 24, 0, 0, 1, tzinfo=ZoneInfo("Asia/Shanghai")),
    )

    assert summary["quality_gates"]["acceptance_eligible"] is True
    assert summary["quality_gates"]["overall_passed"] is True
