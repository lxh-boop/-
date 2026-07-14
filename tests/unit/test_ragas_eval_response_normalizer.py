from __future__ import annotations

from evaluation.ragas_eval.answer_adapter import ProjectAnswerAdapter, answer_metadata
from evaluation.ragas_eval.response_normalizer import normalize_response_for_ragas
from evaluation.ragas_eval.schemas import EvaluationCase
from scoring.schemas import COMPLIANCE_DISCLAIMER


def test_response_normalizer_only_removes_fixed_boilerplate_and_formatting() -> None:
    response = "\n".join(
        [
            "共找到 3 条 RAG 证据。",
            "- [chunk_1] 三六零控股股东计划减持不超5604万股，或套现超5亿元。",
            "- [chunk_2] 该事项可能带来短期风险，但不构成交易建议。",
            COMPLIANCE_DISCLAIMER,
        ]
    )

    normalized = normalize_response_for_ragas(response)

    assert normalized.normalization_method == "deterministic_boilerplate_removal"
    assert "共找到 3 条 RAG 证据。" in normalized.removed_text
    assert COMPLIANCE_DISCLAIMER in normalized.removed_text
    assert "三六零控股股东计划减持不超5604万股" in normalized.evaluated_response
    assert "短期风险" in normalized.evaluated_response
    assert "不构成交易建议" in normalized.evaluated_response
    assert "chunk_1" not in normalized.evaluated_response


def test_response_normalizer_does_not_remove_business_numbers_or_judgements() -> None:
    response = "风险判断：收入下降12.5%，仓位原因是公告风险上升。"

    normalized = normalize_response_for_ragas(response)

    assert normalized.evaluated_response == response
    assert normalized.removed_text == []


def test_answer_adapter_evaluates_captured_response_without_regeneration() -> None:
    response = f"实际回答包含金额3.5亿元。\n{COMPLIANCE_DISCLAIMER}"
    case = EvaluationCase.from_mapping({
        "case_id": "captured_1",
        "user_input": "查询 002468 的公告证据",
        "stock_code": "002468",
        "decision_time": "2026-06-24T15:00:00+08:00",
        "reference": "回购金额下限为3.5亿元。",
        "reference_context_ids": ["chunk_1"],
        "actual_response": response,
        "response_run_id": "agent_run_1",
        "response_source": "production_agent_runtime",
    })

    answer = ProjectAnswerAdapter().generate(case, [])
    metadata = answer_metadata(answer)

    assert answer.response == response
    assert metadata["evaluated_response"] == "实际回答包含金额3.5亿元。"
    assert metadata["normalization_method"] == "deterministic_boilerplate_removal"
