from __future__ import annotations

from agent.intent_decomposition.rule_fallback import decompose_with_rules
from agent.tools.strategy_workflow_tools import (
    IMPLEMENTATION_CONFIRMATION_QUESTION,
    save_strategy_proposal_draft,
)
from strategy_workflow_test_utils import database_path


def test_strategy_llm_failure_keeps_raw_draft_and_asks(tmp_path) -> None:
    decomposition = decompose_with_rules(
        "以后稳健一点",
        warning="missing_api_key",
    )
    task = decomposition.tasks[0]
    result = save_strategy_proposal_draft(
        user_id="u1",
        account_id="paper_u1",
        conversation_id="conv_1",
        original_request="以后稳健一点",
        proposal_json={},
        user_feedback="以后稳健一点",
        conversation_action=task.parameters["conversation_action"],
        db_path=database_path(tmp_path),
    )

    assert task.parameters["conversation_action"] == "llm_unavailable"
    assert result.message == IMPLEMENTATION_CONFIRMATION_QUESTION
    assert result.data["proposal_version"]["proposal_json"] == {
        "original_request": "以后稳健一点",
        "llm_interpretation_required": True,
    }
    assert result.data["implementation_requested"] is False
