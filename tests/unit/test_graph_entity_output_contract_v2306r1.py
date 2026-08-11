from __future__ import annotations

import json

from agent.collaboration.coordinator import AgentCollaborationCoordinator


class _FakeIdentity:
    def __init__(self, lexical_candidates=None) -> None:
        self.lexical_candidates = list(lexical_candidates or [])

    def extract_candidate_mentions(self, query: str):
        del query
        return list(self.lexical_candidates)


class _CaptureLLM:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.kwargs = None

    def generate_json(self, **kwargs):
        self.kwargs = kwargs
        kwargs["validator"](self.payload)
        return self.payload


def _coordinator(payload: dict, *, lexical_candidates=None):
    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator.identity = _FakeIdentity(lexical_candidates)
    coordinator.llm_service = _CaptureLLM(payload)
    return coordinator


def test_portfolio_request_empty_mentions_contract_is_top_level_object_not_array() -> None:
    coordinator = _coordinator({"mentions": []}, lexical_candidates=["我的持仓"])

    result = coordinator._extract_mentions(
        "你认为我的持仓应该怎么调整？",
        "zh",
        context_binding={
            "entity_scope": "portfolio",
            "inherit_previous_focus": False,
        },
    )

    assert result == []
    call = coordinator.llm_service.kwargs
    assert call["stage"] == "graph_entity_candidate_extraction"
    assert call["operation"] == "extract_graph_entity_candidates"
    assert call["disable_thinking"] is True

    system_prompt = call["messages"][0]["content"]
    assert '{"mentions":[]}' in system_prompt
    assert "不得返回顶层数组 []" in system_prompt
    assert "唯一允许的顶层字段为 mentions" in system_prompt
    assert "没有需要 GraphRef 解析的明确对象时返回空数组" not in system_prompt

    user_payload = json.loads(call["messages"][1]["content"])
    assert user_payload["request"] == "你认为我的持仓应该怎么调整？"
    assert user_payload["context_binding"]["entity_scope"] == "portfolio"
    assert user_payload["context_binding"]["inherit_previous_focus"] is False


def test_named_entity_mentions_contract_remains_unchanged() -> None:
    coordinator = _coordinator({"mentions": [{"text": "贵州茅台", "role": "focus"}]})
    result = coordinator._extract_mentions(
        "分析贵州茅台",
        "zh",
        context_binding={"entity_scope": "single_entity", "inherit_previous_focus": False},
    )
    assert result == [{"text": "贵州茅台", "role": "focus"}]


def test_entity_candidate_validator_still_rejects_non_list_mentions() -> None:
    coordinator = _coordinator({"mentions": {"text": "贵州茅台", "role": "focus"}})
    try:
        coordinator._extract_mentions(
            "分析贵州茅台",
            "zh",
            context_binding={"entity_scope": "single_entity"},
        )
    except RuntimeError as exc:
        assert str(exc) == "entity_mentions_not_list"
    else:
        raise AssertionError("invalid mentions payload unexpectedly passed")
