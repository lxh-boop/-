from __future__ import annotations

from strategy_workflow_test_utils import proposal_service, save_draft


def test_strategy_proposal_isolated_across_conversations(tmp_path) -> None:
    first = save_draft(tmp_path, conversation_id="conv_a")
    second = save_draft(tmp_path, conversation_id="conv_b")
    service = proposal_service(tmp_path)

    assert first.data["proposal"]["proposal_id"] != second.data["proposal"]["proposal_id"]
    assert service.get_active(
        user_id="u1",
        account_id="paper_u1",
        conversation_id="conv_a",
    ).proposal_id == first.data["proposal"]["proposal_id"]
    assert service.get_active(
        user_id="u1",
        account_id="paper_u1",
        conversation_id="conv_b",
    ).proposal_id == second.data["proposal"]["proposal_id"]
