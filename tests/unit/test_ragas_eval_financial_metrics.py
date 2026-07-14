from __future__ import annotations

from evaluation.ragas_eval.financial_metrics import calculate_financial_metrics
from evaluation.ragas_eval.schemas import EvaluationCase, RetrievedContext


def _case() -> EvaluationCase:
    return EvaluationCase.from_mapping({
        "case_id": "case_1",
        "user_input": "查询公告风险",
        "stock_code": "300750.SZ",
        "decision_time": "2026-06-20T15:00:00+08:00",
        "reference_context_ids": [],
        "allowed_related_stock_codes": ["002594.SZ"],
    })


def test_financial_metrics_handle_time_stock_duplicate_and_direct_evidence() -> None:
    case = _case()
    contexts = [
        RetrievedContext(
            chunk_id="c1",
            document_id="d1",
            event_id="e1",
            text="宁德时代公告。",
            rank=1,
            stock_codes=["300750"],
            publish_time=None,
            source="上市公司公告",
            metadata={"publish_time": "2026-06-20 10:00:00", "is_announcement": 1},
        ),
        RetrievedContext(
            chunk_id="c2",
            document_id="d2",
            event_id="e2",
            text="未来公告。",
            rank=2,
            stock_codes=["300750"],
            source="交易所公告",
            metadata={"publish_time": "2026-06-20 18:00:00"},
        ),
        RetrievedContext(
            chunk_id="c3",
            document_id="d3",
            event_id="e3",
            text="错误股票公司新闻。",
            rank=3,
            stock_codes=["600519"],
            source="公司新闻",
            metadata={"publish_time": "2026-06-19 09:00:00"},
        ),
        RetrievedContext(
            chunk_id="c4",
            document_id="d4",
            event_id="e4",
            text="行业新闻不直接算错股。",
            rank=4,
            stock_codes=["600519"],
            source="行业新闻",
            metadata={"publish_time": "2026-06-19 09:00:00", "context_scope": "industry"},
        ),
        RetrievedContext(
            chunk_id="c5",
            document_id="d5",
            event_id="e1",
            text="同一事件重复。",
            rank=5,
            stock_codes=["300750"],
            source="公司公告",
            metadata={},
        ),
    ]

    metrics = calculate_financial_metrics(case, contexts, response="共找到证据。")

    assert metrics["future_leak_count"] == 1
    assert metrics["future_leak_rate"] == 1 / 4
    assert metrics["missing_publish_time_count"] == 1
    assert metrics["wrong_stock_count"] == 1
    assert metrics["wrong_stock_chunk_ids"] == ["c3"]
    assert metrics["duplicate_event_count"] == 1
    assert metrics["duplicate_event_rate"] == 1 / 5
    assert metrics["direct_evidence_count"] == 3
    assert metrics["direct_evidence_rate"] == 3 / 5
    assert metrics["unsupported_position_reason_status"] == "not_applicable"


def test_position_reason_metric_returns_not_available_instead_of_fake_number() -> None:
    metrics = calculate_financial_metrics(_case(), [], response="建议说明仓位调整原因。")

    assert metrics["unsupported_position_reason_rate"] is None
    assert metrics["unsupported_position_reason_status"] == "not_available"
