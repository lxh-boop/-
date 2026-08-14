from __future__ import annotations

from agent.collaboration.coordinator import AgentCollaborationCoordinator
from agent.graph.contracts import GraphRef


def _security_ref() -> GraphRef:
    return GraphRef(
        graph_id="financial_graph",
        node_id="cn:security:sse:600519",
        node_kind="object",
        role="focus",
        source="neo4j_exact_identity",
        confidence=1.0,
        locked=True,
    )


def test_typed_security_focus_resolves_deictic_reference_after_portfolio_turn() -> None:
    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator._extract_mentions = lambda query, language, context_binding=None: []
    focus, missing, audit = coordinator._resolve_request_refs(
        query="把刚刚那只股票加到我的持仓怎么样？",
        inherited_refs=[],
        typed_inherited_refs=[_security_ref()],
        context_refs=[],
        as_of_time="",
        language="zh",
        context_binding={
            "entity_scope": "conversation_focus",
            "inherit_previous_focus": True,
            "reference_entity_type": "security",
        },
    )
    assert [ref.node_id for ref in focus] == ["cn:security:sse:600519"]
    assert missing == []
    assert audit["typed_focus_source_count"] == 1


def test_deictic_security_reference_blocks_planning_when_no_typed_focus_exists() -> None:
    coordinator = AgentCollaborationCoordinator.__new__(AgentCollaborationCoordinator)
    coordinator._extract_mentions = lambda query, language, context_binding=None: []
    focus, missing, _ = coordinator._resolve_request_refs(
        query="把刚刚那只股票加到我的持仓怎么样？",
        inherited_refs=[],
        typed_inherited_refs=[],
        context_refs=[],
        as_of_time="",
        language="zh",
        context_binding={
            "entity_scope": "conversation_focus",
            "inherit_previous_focus": True,
            "reference_entity_type": "security",
        },
    )
    assert focus == []
    assert [item.key for item in missing] == ["unresolved_conversation_security"]
