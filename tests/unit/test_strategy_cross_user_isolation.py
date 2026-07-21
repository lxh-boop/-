from __future__ import annotations

from strategy_workflow_test_utils import proposal_service, save_draft


def test_strategy_proposal_isolated_across_users(tmp_path) -> None:
    first = save_draft(tmp_path, user_id="u1", account_id="paper_u1")
    second = save_draft(tmp_path, user_id="u2", account_id="paper_u2")
    service = proposal_service(tmp_path)

    assert first.data["proposal"]["proposal_id"] != second.data["proposal"]["proposal_id"]
    assert service.get(first.data["proposal"]["proposal_id"], user_id="u2") is None
    assert service.list_versions(
        first.data["proposal"]["proposal_id"],
        user_id="u2",
    ) == []
