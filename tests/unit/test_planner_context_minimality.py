from __future__ import annotations

from agent.context.context_types import ContextBundle, MemoryContext
from agent.context.planner_context_factory import build_planner_context


def test_planner_context_excludes_runtime_and_mcp_payloads():
    bundle = ContextBundle(
        user_id="u1",
        conversation_id="c1",
        run_id="r1",
        memory_context=MemoryContext(
            retrieval_id="memret_1",
            memory_refs=["m1"],
            items=[{"memory": {"memory_id": "m1", "summary": "稳健偏好"}, "score": 0.8}],
            selected_count=1,
            candidate_count=20,
            threshold_pass_count=1,
            relevance_threshold=0.42,
            token_budget=360,
            token_used=20,
        ),
    )
    context = build_planner_context(
        bundle,
        turn_context={
            "current_message": "分析 600519",
            "follow_up": {"is_follow_up": False},
            "runtime_policy": {"secret": "should_not_enter"},
            "mcp": {"servers": ["should_not_enter"]},
            "agent_context": {"compressed_text": "should_not_enter"},
            "context_bundle_llm": {"huge": True},
        },
    )
    assert "runtime_policy" not in context
    assert "mcp" not in context
    assert "agent_context" not in context
    assert "context_bundle_llm" not in context
    assert context["memory_context"]["retrieval_id"] == "memret_1"
