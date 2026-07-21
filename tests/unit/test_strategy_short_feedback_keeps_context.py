from __future__ import annotations

from agent.intent_decomposition.rule_fallback import decompose_with_rules
from agent.services.strategy_context_service import StrategyContextService
from strategy_workflow_test_utils import database_path, save_draft


def test_strategy_short_feedback_routes_to_active_proposal_context(tmp_path) -> None:
    save_draft(tmp_path)
    context = StrategyContextService(
        db_path=database_path(tmp_path),
        output_dir=tmp_path / "outputs",
    ).load(
        user_id="u1",
        account_id="paper_u1",
        conversation_id="conv_1",
    )

    decomposition = decompose_with_rules(
        "现金少一点",
        warning="missing_api_key",
        context={"strategy_conversation_context": context.to_dict()},
    )

    assert decomposition.tasks[0].intent == "strategy_change"
    assert decomposition.tasks[0].operation_type == "strategy_change"
    assert (
        decomposition.tasks[0].parameters["proposal_id"]
        == context.active_proposal["proposal_id"]
    )
