from __future__ import annotations

from agent.memory.memory_context_selector import MemoryContextSelector
from agent.memory.memory_retrieval_types import MemoryRetrievalRequest
from agent.memory.memory_retriever import MemorySearchResult
from agent.memory.memory_types import MemoryRecord, MemoryScope, MemoryStatus, MemoryType


def _result(memory_id: str, summary: str, score: float, *, stock_codes=None, subtype="preference"):
    record = MemoryRecord(
        memory_id=memory_id,
        user_id="u1",
        memory_type=MemoryType.SEMANTIC,
        memory_subtype=subtype,
        scope=MemoryScope.USER,
        status=MemoryStatus.ACTIVE,
        summary=summary,
        content=summary,
        stock_codes=list(stock_codes or []),
        importance=0.8,
        confidence=0.9,
        metadata={"user_confirmed": True},
    )
    return MemorySearchResult(record=record, score=score, score_parts={"semantic": score})


def test_context_can_contain_zero_memories_when_threshold_not_met():
    selector = MemoryContextSelector()
    request = MemoryRetrievalRequest(
        user_id="u1",
        query="分析 600519",
        stock_codes=["600519"],
        candidate_top_n=40,
        relevance_threshold=0.95,
        token_budget=300,
    )
    result = selector.select(
        [_result("m1", "用户喜欢低换手", 0.2)],
        request,
    )
    assert result.selected == []
    assert result.diagnostics is not None
    assert result.diagnostics.candidate_count == 1
    assert result.diagnostics.selected_count == 0


def test_entity_mismatch_is_rejected_but_general_preference_can_pass():
    selector = MemoryContextSelector()
    request = MemoryRetrievalRequest(
        user_id="u1",
        query="分析股票 600519 的风险",
        stock_codes=["600519"],
        task_type="stock_analysis",
        relevance_threshold=0.35,
        token_budget=300,
    )
    result = selector.select(
        [
            _result("m_wrong", "600000 的历史决策", 0.9, stock_codes=["600000"], subtype="decision"),
            _result("m_general", "用户长期偏好稳健和较低集中度", 0.7),
        ],
        request,
    )
    ids = [(item.get("memory") or {}).get("memory_id") for item in result.selected]
    assert "m_wrong" not in ids
    assert "m_general" in ids


def test_token_budget_filters_after_threshold():
    selector = MemoryContextSelector()
    request = MemoryRetrievalRequest(
        user_id="u1",
        query="组合风险",
        task_type="portfolio",
        relevance_threshold=0.2,
        token_budget=70,
    )
    candidates = [
        _result(f"m{index}", "用户稳健偏好 " + ("说明" * 80), 0.8 - index * 0.01)
        for index in range(5)
    ]
    result = selector.select(candidates, request)
    assert result.diagnostics is not None
    assert result.diagnostics.threshold_pass_count >= result.diagnostics.selected_count
    assert result.diagnostics.token_used <= request.token_budget
