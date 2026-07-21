from __future__ import annotations

import pytest

from agent.intent_decomposition import layered_decomposer
from agent.intent_decomposition.llm_decomposer import (
    IntentDecompositionError,
)


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("LLM request timed out"),
        IntentDecompositionError("invalid JSON response"),
        RuntimeError("insufficient balance"),
    ],
)
def test_strategy_llm_fault_never_auto_implements(
    monkeypatch,
    error,
) -> None:
    def fail_llm(*args, **kwargs):
        raise error

    monkeypatch.setattr(
        layered_decomposer,
        "decompose_with_llm",
        fail_llm,
    )
    result = layered_decomposer.decompose_intent(
        "把长期模拟盘策略改得更稳健并立即实施",
        llm_api_key="test-key",
        enable_llm=True,
        context={
            "user_id": "u1",
            "account_id": "paper_u1",
            "conversation_id": "conv_fault",
        },
    )

    assert not any(
        task.intent
        in {
            "strategy_prepare_implementation",
            "strategy_create_apply_plan",
            "strategy_apply_commit",
            "strategy_create_activation_plan",
            "strategy_binding_commit",
            "strategy_preview_position_change",
            "strategy_position_commit",
        }
        for task in result.tasks
    )
    assert not any(
        task.parameters.get("conversation_action")
        == "prepare_implementation"
        for task in result.tasks
    )
    assert result.diagnostics.get("fallback_used") is not False or (
        result.diagnostics.get("error_code") == "insufficient_balance"
    )

